"""Bot Telegram per gruppo - indicizza ristoranti e cerca per vicinanza."""
import json, os, re, math, logging
from pathlib import Path
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from geopy.geocoders import Nominatim
from geopy.distance import geodesic

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8961858964:AAF5R38A6qTTTr0OMkUmZOe1K2RkMuCvV0o")
if not TOKEN:
    raise SystemExit("TELEGRAM_BOT_TOKEN not set. Add it as env variable or in .env file.")
DB_PATH = Path(__file__).parent / "db.json"
geolocator = Nominatim(user_agent="trattoria_bot")


def load_db() -> list[dict]:
    if DB_PATH.exists():
        return json.loads(DB_PATH.read_text(encoding="utf-8"))
    return []


def save_db(db: list[dict]):
    DB_PATH.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_review(text: str) -> dict | None:
    """Estrae nome, zona, prezzo e piatti da un testo di recensione."""
    info = {"nome": None, "zona": None, "prezzo": None, "piatti": [], "testo": text}

    # Nome: cerca pattern comuni
    # "Sono stato al/alla/all' NOME" o "NOME" tra apici/virgolette
    m = re.search(r"(?:stato|andat[oa]|provato|mangiato)\s+(?:al(?:l[''a]?)?|da)\s+([A-Z][A-Za-zÀ-ú\s'']+)", text)
    if m:
        info["nome"] = m.group(1).strip().rstrip(".,;!")
    if not info["nome"]:
        m = re.search(r"[\"'«]([A-Z][A-Za-zÀ-ú\s'']+)[\"'»]", text)
        if m:
            info["nome"] = m.group(1).strip()

    # Zona: cerca "Zona X" o "(Zona X)" o città tra parentesi
    m = re.search(r"\(?[Zz]ona\s+([A-Za-zÀ-ú\s]+)\)?", text)
    if m:
        info["zona"] = m.group(1).strip().rstrip(")")
    if not info["zona"]:
        m = re.search(r"(ROMA|Roma|Milano|Napoli|Torino|Firenze|Bologna)[^)]*\(([^)]+)\)", text)
        if m:
            info["zona"] = m.group(2).strip()
        elif re.search(r"(ROMA|Roma|Milano|Napoli|Torino|Firenze|Bologna)", text):
            info["zona"] = re.search(r"(ROMA|Roma|Milano|Napoli|Torino|Firenze|Bologna)", text).group(1)

    # Prezzo: cerca €, euro, "X a testa"
    m = re.search(r"(\d+)[€\s]*(?:a testa|euro|€)", text)
    if m:
        info["prezzo"] = int(m.group(1))
    if not info["prezzo"]:
        m = re.search(r"(?:meno di|circa|sui)\s*(\d+)\s*€", text)
        if m:
            info["prezzo"] = int(m.group(1))

    # Piatti: cerca lista con "-" o "•"
    piatti = re.findall(r"[-•]\s*(.+)", text)
    info["piatti"] = [p.strip() for p in piatti[:6]]

    return info if info["nome"] else None


def geocode_place(nome: str, zona: str | None) -> tuple[float, float] | None:
    """Geocodifica un ristorante."""
    queries = []
    if zona:
        queries.append(f"{nome}, {zona}, Italia")
        queries.append(f"{nome}, {zona}")
    queries.append(f"{nome}, Italia")
    queries.append(nome)

    for q in queries:
        try:
            loc = geolocator.geocode(q, timeout=10)
            if loc:
                return (loc.latitude, loc.longitude)
        except Exception:
            continue
    return None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🍝 *Trattoria Bot*\n\n"
        "Incolla una recensione e la salvo con posizione.\n"
        "Manda la tua 📍 posizione per trovare i posti più vicini.\n\n"
        "Comandi:\n"
        "/vicino - manda posizione dopo questo comando\n"
        "/lista - tutti i posti salvati\n"
        "/cerca <testo> - cerca per nome/zona\n"
        "/stats - statistiche",
        parse_mode="Markdown"
    )


async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quando qualcuno manda la posizione, mostra i posti più vicini."""
    user_loc = (update.message.location.latitude, update.message.location.longitude)
    db = load_db()
    if not db:
        await update.message.reply_text("Nessun posto salvato ancora!")
        return

    # Calcola distanze
    results = []
    for place in db:
        if place.get("lat") and place.get("lon"):
            dist = geodesic(user_loc, (place["lat"], place["lon"])).km
            results.append((dist, place))

    if not results:
        await update.message.reply_text("Nessun posto con coordinate. Aggiungi recensioni!")
        return

    results.sort(key=lambda x: x[0])
    top = results[:5]

    msg = "📍 *Posti più vicini:*\n\n"
    for i, (dist, p) in enumerate(top, 1):
        prezzo = f" · ~{p['prezzo']}€" if p.get("prezzo") else ""
        msg += f"{i}. *{p['nome']}*{prezzo}\n"
        msg += f"   📏 {dist:.1f} km"
        if p.get("zona"):
            msg += f" · {p['zona']}"
        msg += "\n"
        if p.get("piatti"):
            msg += f"   🍽️ {', '.join(p['piatti'][:3])}\n"
        msg += "\n"

    await update.message.reply_text(msg, parse_mode="Markdown")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quando qualcuno scrive testo, prova a parsarlo come recensione."""
    text = update.message.text
    if not text or len(text) < 50:
        return  # Ignora messaggi corti

    info = parse_review(text)
    if not info:
        return  # Non sembra una recensione

    # Geocodifica
    coords = geocode_place(info["nome"], info["zona"])

    entry = {
        "nome": info["nome"],
        "zona": info["zona"],
        "prezzo": info["prezzo"],
        "piatti": info["piatti"],
        "lat": coords[0] if coords else None,
        "lon": coords[1] if coords else None,
        "aggiunto_da": update.message.from_user.first_name,
        "data": update.message.date.isoformat(),
    }

    db = load_db()
    # Evita duplicati per nome
    if not any(p["nome"].lower() == entry["nome"].lower() for p in db):
        db.append(entry)
        save_db(db)
        geo_status = "📍 Posizione trovata!" if coords else "⚠️ Posizione non trovata (aggiungi manualmente)"
        await update.message.reply_text(
            f"✅ *{entry['nome']}* salvato!\n"
            f"📍 {entry['zona'] or 'Zona non specificata'}\n"
            f"💰 {'~' + str(entry['prezzo']) + '€' if entry['prezzo'] else 'Prezzo non specificato'}\n"
            f"{geo_status}",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(f"ℹ️ *{entry['nome']}* è già nel database!", parse_mode="Markdown")


async def lista(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = load_db()
    if not db:
        await update.message.reply_text("Nessun posto salvato!")
        return
    msg = "📋 *Tutti i posti:*\n\n"
    for i, p in enumerate(db, 1):
        prezzo = f" · ~{p['prezzo']}€" if p.get("prezzo") else ""
        geo = " 📍" if p.get("lat") else " ❌🗺️"
        msg += f"{i}. *{p['nome']}*{prezzo}{geo}\n"
        if p.get("zona"):
            msg += f"   {p['zona']}\n"
    await update.message.reply_text(msg, parse_mode="Markdown")


async def cerca(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args).lower() if context.args else ""
    if not query:
        await update.message.reply_text("Uso: /cerca <nome o zona>")
        return
    db = load_db()
    results = [p for p in db if query in p.get("nome", "").lower() or query in (p.get("zona") or "").lower()]
    if not results:
        await update.message.reply_text(f"Nessun risultato per '{query}'")
        return
    msg = f"🔍 *Risultati per '{query}':*\n\n"
    for p in results:
        prezzo = f" · ~{p['prezzo']}€" if p.get("prezzo") else ""
        msg += f"• *{p['nome']}*{prezzo}\n"
        if p.get("piatti"):
            msg += f"  🍽️ {', '.join(p['piatti'][:3])}\n"
    await update.message.reply_text(msg, parse_mode="Markdown")


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = load_db()
    if not db:
        await update.message.reply_text("Nessun dato!")
        return
    geo_count = sum(1 for p in db if p.get("lat"))
    prezzi = [p["prezzo"] for p in db if p.get("prezzo")]
    avg = sum(prezzi) / len(prezzi) if prezzi else 0
    msg = (
        f"📊 *Statistiche:*\n\n"
        f"🍽️ Posti salvati: {len(db)}\n"
        f"📍 Con posizione: {geo_count}/{len(db)}\n"
        f"💰 Prezzo medio: ~{avg:.0f}€\n"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("lista", lista))
    app.add_handler(CommandHandler("cerca", cerca))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(MessageHandler(filters.LOCATION, handle_location))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    logger.info("Bot avviato!")
    app.run_polling()


if __name__ == "__main__":
    main()
