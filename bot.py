import logging
import os
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")  # or just paste "123456:..." here for testing

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Simple in-memory storage (for educational demo only - lost on restart)
user_states = {}  # user_id → {"phone": "...", "stage": "waiting_otp"}

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
        del user_states[user_id]  # clean up
    else:
        await update.message.reply_text("Please enter exactly 6 digits.")

def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("id", id_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_otp_input))

    print("Bot is starting... (fake OTP educational demo)")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()