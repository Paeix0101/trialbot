import os
import logging
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_TOKEN = os.getenv("API_TOKEN") or "xpol_Randi_53f66910"

BASE_URL = "https://xpolitesupgrade-api.darrify-api.workers.dev/api"


# ==================== Helper Function ====================
def format_response(data):
    """Saare possible keys ko sundar format mein convert karta hai"""
    if not isinstance(data, dict):
        return str(data)

    text = ""
    for key, value in data.items():
        if value is None or value == "" or value == {} or value == []:
            continue  # Khali fields skip kar do
        
        # Agar value dict hai to usko bhi format karo
        if isinstance(value, dict):
            text += f"**{key.replace('_', ' ').title()}**\n"
            for k, v in value.items():
                if v:
                    text += f"▸ {k.replace('_', ' ').title()}: `{v}`\n"
            text += "\n"
        else:
            text += f"**{key.replace('_', ' ').title()}**: `{value}`\n"
    
    return text.strip() or "No data found"


# ==================== IP INFO ====================
async def ipinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("❌ Usage: `/ip <ip_address>`", parse_mode="Markdown")
        return

    ip = context.args[0]
    await update.message.reply_text("🔍 IP Info dhund raha hu...")

    try:
        url = f"{BASE_URL}/ipinfo?token={API_TOKEN}&ip={ip}"
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()

        result = format_response(data)
        await update.message.reply_text(result, parse_mode="Markdown")
        
    except Exception as e:
        logger.error(e)
        await update.message.reply_text(f"❌ Error: {str(e)}")


# ==================== IFSC RAZOR ====================
async def ifsc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("❌ Usage: `/ifsc <ifsc_code>`", parse_mode="Markdown")
        return

    ifsc_code = context.args[0].upper()
    await update.message.reply_text("🏦 IFSC Details dhund raha hu...")

    try:
        url = f"{BASE_URL}/ifsc-razor?token={API_TOKEN}&ifsc={ifsc_code}"
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()

        result = format_response(data)
        await update.message.reply_text(result, parse_mode="Markdown")
        
    except Exception as e:
        logger.error(e)
        await update.message.reply_text(f"❌ Error: {str(e)}")


# ==================== IFSC ADV ====================
async def ifscadv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("❌ Usage: `/ifscadv <ifsc_code>`", parse_mode="Markdown")
        return

    ifsc_code = context.args[0].upper()
    await update.message.reply_text("🔎 Advanced IFSC Details dhund raha hu...")

    try:
        url = f"{BASE_URL}/ifsc-adv?token={API_TOKEN}&ifsc={ifsc_code}"
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()

        result = format_response(data)
        await update.message.reply_text(result, parse_mode="Markdown")
        
    except Exception as e:
        logger.error(e)
        await update.message.reply_text(f"❌ Error: {str(e)}")


# ==================== START ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ **Bot Online**\n\n"
        "Commands:\n"
        "• `/ip <ip>`\n"
        "• `/ifsc <ifsc>`\n"
        "• `/ifscadv <ifsc>`",
        parse_mode="Markdown"
    )


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ip", ipinfo))
    app.add_handler(CommandHandler("ifsc", ifsc))
    app.add_handler(CommandHandler("ifscadv", ifscadv))

    print("🤖 Bot Started...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()