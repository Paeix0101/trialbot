import os
import logging
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Logging setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_TOKEN = "xpol_Randi_53f66910"   # Better to put in env variable

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable set nahi hai!")

# ==================== IP INFO ====================
async def ipinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("❌ Usage: `/ip <ip_address>`", parse_mode="Markdown")
        return

    ip = context.args[0]

    try:
        url = f"https://xpolitesupgrade-api.darrify-api.workers.dev/api/ipinfo?token={API_TOKEN}&ip={ip}"
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()

        await update.message.reply_text(f"```{data}```", parse_mode="Markdown")
        
    except Exception as e:
        logger.error(e)
        await update.message.reply_text(f"❌ Error: {str(e)}")


# ==================== IFSC ====================
async def ifsc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("❌ Usage: `/ifsc <ifsc_code>`", parse_mode="Markdown")
        return

    ifsc_code = context.args[0].upper()

    try:
        url = f"https://xpolitesupgrade-api.darrify-api.workers.dev/api/ifsc-razor?token={API_TOKEN}&ifsc={ifsc_code}"
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()

        await update.message.reply_text(f"```{data}```", parse_mode="Markdown")
        
    except Exception as e:
        logger.error(e)
        await update.message.reply_text(f"❌ Error: {str(e)}")


# ==================== IFSC ADV ====================
async def ifscadv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("❌ Usage: `/ifscadv <ifsc_code>`", parse_mode="Markdown")
        return

    ifsc_code = context.args[0].upper()

    try:
        url = f"https://xpolitesupgrade-api.darrify-api.workers.dev/api/ifsc-adv?token={API_TOKEN}&ifsc={ifsc_code}"
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()

        await update.message.reply_text(f"```{data}```", parse_mode="Markdown")
        
    except Exception as e:
        logger.error(e)
        await update.message.reply_text(f"❌ Error: {str(e)}")


# ==================== START ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ **Bot Online**\n\n"
        "Available Commands:\n"
        "• `/ip <ip_address>`\n"
        "• `/ifsc <ifsc_code>`\n"
        "• `/ifscadv <ifsc_code>`",
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