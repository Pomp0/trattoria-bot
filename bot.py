"""Bot Telegram per gruppo - indicizza ristoranti con LLM parsing."""
import json, os, logging
from pathlib import Path
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
from groq import Groq

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8961858964:AAE7m2Zm6KzCZBLtsPvYYNSPAP4BqHwDQvk")
GROQ_KEY = os.environ.get("GROQ_API_KEY", "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")

DB_PATH = Path(__file__).parent / "db.json"
geolocator = Nominatim(user_agent="trattoria_bot")
groq_client = Groq(api_key=GROQ_KEY)


def load_db() -> list[dict]:
    if DB_PATH.exists():
        return json.loads(DB_PATH.read_text(encoding="utf-8"))
    return []


def save_db(db: list[dict]):
    DB_PATH.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_review_llm(text: str) -> dict | None:
    """Usa Groq LLM per estrarre info dal testo."""
    try:
        resp = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{
                "role": "system",
                "content": "Estrai info ristorante dal testo. Rispondi SOLO con JSON valido: {\"nome\": str, \"indirizzo\": str or null, \"citta\": str or null, \"zona\": str or null, \"prezzo_persona\": int or null, \"piatti\": [str]}. Se non è una recensione ristorante rispondi {\"nome\": null}"
            }, {
                "role": "user",
                "content": text
            }],
            temperature=0,
            max_tokens=300
        )
        raw = resp.choices[0].message.content.strip()
        # Estrai JSON anche se c'è testo attorno
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(raw[start:end])
            if data.get("nome"):
                return data
    except Exception as e:
        logger.error(f"LLM parse error: {e}")
    return None


def geocode_place(info: dict) -> tuple[float, float] | None:
    """Geocodifica usando indirizzo, zona o città."""
    queries = []
    nome = info.get("nome", "")
    indirizzo = info.get("indirizzo")
    citta = info.get("citta")
    zona = info.get("zona")

    if indirizzo and citta:
        queries.append(f"{indirizzo}, {citta}, Italia")
    if indirizzo:
        queries.append(f"{indirizzo}, Italia")
    if nome and citta:
        queries.append(f"{nome}, {citta}, Italia")
    if zona and citta:
        queries.append(f"{zona}, {citta}, Italia")
    if zona:
        queries.append(f"{zona}, Italia")
    if citta:
        queries.append(f"{citta}, Italia")

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
        "/lista - tutti i posti salvati\n"
        "/cerca <testo> - cerca per nome/zona/città\n"
        "/elimina - rimuovi un posto\n"
        "/stats - statistiche",
        parse_mode="Markdown"
    )


async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_loc = (update.message.location.latitude, update.message.location.longitude)
    db = load_db()
    if not db:
        await update.message.reply_text("Nessun posto salvato ancora!")
        return
    results = []
    for place in db:
        if place.get("lat") and place.get("lon"):
            dist = geodesic(user_loc, (place["lat"], place["lon"])).km
            results.append((dist, place))
    if not results:
        await update.message.reply_text("Nessun posto con coordinate!")
        return
    results.sort(key=lambda x: x[0])
    msg = "📍 *Posti più vicini:*\n\n"
    for i, (dist, p) in enumerate(results[:5], 1):
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
    text = update.message.text
    if not text or len(text) < 50:
        return

    info = parse_review_llm(text)
    if not info:
        return

    coords = geocode_place(info)
    zona_display = info.get("indirizzo") or info.get("zona") or info.get("citta")

    entry = {
        "nome": info["nome"],
        "zona": zona_display,
        "citta": info.get("citta"),
        "prezzo": info.get("prezzo_persona"),
        "piatti": info.get("piatti", []),
        "lat": coords[0] if coords else None,
        "lon": coords[1] if coords else None,
        "aggiunto_da": update.message.from_user.first_name,
        "data": update.message.date.isoformat(),
    }

    db = load_db()
    if not any(p["nome"].lower() == entry["nome"].lower() for p in db):
        db.append(entry)
        save_db(db)
        geo_status = "📍 Posizione trovata!" if coords else "⚠️ Posizione non trovata"
        piatti_str = "\n🍽️ " + ", ".join(entry["piatti"][:4]) if entry["piatti"] else ""
        await update.message.reply_text(
            f"✅ *{entry['nome']}* salvato!\n"
            f"📍 {zona_display or 'N/A'}\n"
            f"💰 {'~' + str(entry['prezzo']) + '€/persona' if entry['prezzo'] else 'N/A'}"
            f"{piatti_str}\n"
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
        geo = " 📍" if p.get("lat") else ""
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
    results = [p for p in db if query in p.get("nome", "").lower() or query in (p.get("zona") or "").lower() or query in (p.get("citta") or "").lower()]
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
    await update.message.reply_text(
        f"📊 *Statistiche:*\n\n"
        f"🍽️ Posti salvati: {len(db)}\n"
        f"📍 Con posizione: {geo_count}/{len(db)}\n"
        f"💰 Prezzo medio: ~{avg:.0f}€\n",
        parse_mode="Markdown"
    )


async def elimina(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        db = load_db()
        if not db:
            await update.message.reply_text("Nessun posto salvato!")
            return
        msg = "🗑️ *Quale vuoi eliminare?*\n\n"
        for i, p in enumerate(db, 1):
            msg += f"{i}. {p['nome']}\n"
        msg += "\nUsa: `/elimina <numero>`"
        await update.message.reply_text(msg, parse_mode="Markdown")
        return
    try:
        idx = int(context.args[0]) - 1
        db = load_db()
        if 0 <= idx < len(db):
            removed = db.pop(idx)
            save_db(db)
            await update.message.reply_text(f"🗑️ *{removed['nome']}* eliminato!", parse_mode="Markdown")
        else:
            await update.message.reply_text("Numero non valido!")
    except ValueError:
        await update.message.reply_text("Uso: `/elimina <numero>`", parse_mode="Markdown")


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("lista", lista))
    app.add_handler(CommandHandler("cerca", cerca))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("elimina", elimina))
    app.add_handler(MessageHandler(filters.LOCATION, handle_location))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    logger.info("Bot avviato!")
    app.run_polling()


if __name__ == "__main__":
    main()
