# bot.py  (rename to app.py if you prefer — Render auto-detects Flask apps)
import logging
import os
import threading
from dotenv import load_dotenv

from flask import Flask, request, jsonify

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")  # Set this in Render → Environment Variables

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In-memory storage (educational only)
user_states = {}

# ── Your handlers (same as before, just copy-pasted for completeness) ──
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi! This is a **fake / educational OTP demo bot**.\n"
        "Send /id +919876543210 (just for learning how buttons & states work)"
    )

async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /id +919876543210")
        return
    phone = " ".join(context.args).strip()
    if not phone.startswith("+"):
        phone = "+" + phone
    user_id = update.effective_user.id
    user_states[user_id] = {"phone": phone, "stage": "shown_number"}
    keyboard = [[InlineKeyboardButton("Verify ✅", callback_data="verify")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"Number: {phone}\n\n"
        "**THIS IS A FAKE EDUCATIONAL DEMO ONLY**\n"
        "No real OTP will be sent!",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if user_id not in user_states or user_states[user_id]["stage"] != "shown_number":
        await query.edit_message_text("Session expired or invalid.")
        return
    phone = user_states[user_id]["phone"]
    user_states[user_id]["stage"] = "waiting_otp"
    await query.edit_message_text(
        f"**FAKE OTP demo** — pretend we sent code to {phone}\n\n"
        "Enter the 6-digit code you 'received':\n"
        "(just type any 6 digits — it's not real)"
    )

async def handle_otp_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_states or user_states[user_id]["stage"] != "waiting_otp":
        return
    text = update.message.text.strip()
    if text.isdigit() and len(text) == 6:
        phone = user_states[user_id]["phone"]
        await update.message.reply_text(
            f"**FAKE verification result**\n"
            f"You entered: {text}\n"
            f"For number: {phone}\n\n"
            "→ In real scam bots this would say 'Wrong OTP' or 'Success'.\n"
            "This is only educational — nothing actually happened."
        )
        del user_states[user_id]
    else:
        await update.message.reply_text("Please enter exactly 6 digits.")

# ── Flask part ──
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "Telegram OTP Demo Bot is running! (educational only)"

@flask_app.route("/health")
def health():
    return jsonify({"status": "alive", "users_in_session": len(user_states)})

# ── Run Telegram polling in background thread ──
def run_telegram_bot():
    try:
        application = Application.builder().token(TOKEN).build()

        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("id", id_command))
        application.add_handler(CallbackQueryHandler(button_handler))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_otp_input))

        print("Starting Telegram polling in background thread...")
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
            poll_interval=1.0,          # adjust if needed
        )
    except Exception as e:
        logger.error(f"Telegram bot crashed: {e}")

if __name__ == "__main__":
    # Start Telegram in a separate thread
    bot_thread = threading.Thread(target=run_telegram_bot, daemon=True)
    bot_thread.start()

    # Start Flask (Render will use this as entry point)
    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port, debug=False)