import os
import logging
import asyncio
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_TOKEN = os.getenv("API_TOKEN") or "xpol_Randi_53f66910"

BASE_URL = "https://xpolitesupgrade-api.darrify-api.workers.dev/api"


def format_response(data):
    if not isinstance(data, dict):
        return str(data)
    text = ""
    for key, value in data.items():
        if value in [None, "", {}, []]:
            continue
        if isinstance(value, dict):
            text += f"**{key.replace('_', ' ').title()}**\n"
            for k, v in value.items():
                if v not in [None, "", {}, []]:
                    text += f"▸ {k.replace('_', ' ').title()}: `{v}`\n"
            text += "\n"
        else:
            text += f"**{key.replace('_', ' ').title()}**: `{value}`\n"
    return text.strip() or "No data found"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Bot Online!\n\nUse: /ip , /ifsc , /ifscadv", parse_mode="Markdown")

async def ipinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1: return await update.message.reply_text("❌ /ip <ip>")
    ip = context.args[0]
    try:
        r = requests.get(f"{BASE_URL}/ipinfo?token={API_TOKEN}&ip={ip}", timeout=15)
        r.raise_for_status()
        await update.message.reply_text(format_response(r.json()), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def ifsc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1: return await update.message.reply_text("❌ /ifsc <ifsc>")
    code = context.args[0].upper()
    try:
        r = requests.get(f"{BASE_URL}/ifsc-razor?token={API_TOKEN}&ifsc={code}", timeout=15)
        r.raise_for_status()
        await update.message.reply_text(format_response(r.json()), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def ifscadv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1: return await update.message.reply_text("❌ /ifscadv <ifsc>")
    code = context.args[0].upper()
    try:
        r = requests.get(f"{BASE_URL}/ifsc-adv?token={API_TOKEN}&ifsc={code}", timeout=15)
        r.raise_for_status()
        await update.message.reply_text(format_response(r.json()), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ip", ipinfo))
    app.add_handler(CommandHandler("ifsc", ifsc))
    app.add_handler(CommandHandler("ifscadv", ifscadv))

    print("Bot Started...")
    app.run_polling()


if __name__ == "__main__":
    asyncio.run(main())