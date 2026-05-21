# 🍝 Trattoria Bot

Bot Telegram per gruppo — indicizza ristoranti da recensioni testuali e cerca per vicinanza.

## Setup

1. Crea un bot su Telegram via [@BotFather](https://t.me/BotFather) e copia il token
2. Installa dipendenze:
   ```
   pip install -r requirements.txt
   ```
3. Lancia:
   ```
   set TELEGRAM_BOT_TOKEN=il_tuo_token
   python bot.py
   ```
4. Aggiungi il bot al gruppo

## Uso

- **Incolla una recensione** → il bot estrae nome, zona, prezzo, piatti e geocodifica
- **Manda la tua posizione** 📍 → ti mostra i 5 posti più vicini
- `/lista` — tutti i posti salvati
- `/cerca roma` — cerca per nome o zona
- `/stats` — statistiche

## Come funziona il parsing

Il bot cerca nel testo:
- Nome: "Sono stato al/alla **Nome**" o testo tra virgolette
- Zona: "Zona X" o città tra parentesi
- Prezzo: numeri seguiti da € o "a testa"
- Piatti: righe che iniziano con `-` o `•`

## Prossimi step

- [ ] OCR da foto scontrino
- [ ] Foto piatti associate al locale
- [ ] Voto 1-5 stelle
- [ ] Export mappa HTML
