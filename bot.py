import os
import logging
import asyncio
import requests
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import threading

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_TOKEN = os.getenv("API_TOKEN") or "xpol_Randi_53f66910"
BASE_URL = "https://xpolitesupgrade-api.darrify-api.workers.dev/api"

app = Flask(__name__)

def format_response(data, indent=0):
    """Recursively format nested JSON response"""
    if not isinstance(data, dict):
        return str(data)
    
    text = ""
    prefix = "  " * indent
    
    for key, value in data.items():
        if key in ["developer"]:
            continue
        if value in [None, "", {}, []]:
            continue
            
        if isinstance(value, dict):
            text += f"{prefix}**{key.replace('_', ' ').title()}**\n"
            text += format_response(value, indent + 1)
        elif isinstance(value, list):
            text += f"{prefix}**{key.replace('_', ' ').title()}**\n"
            for item in value:
                if isinstance(item, dict):
                    text += format_response(item, indent + 1)
                else:
                    text += f"{prefix}  ▸ `{item}`\n"
        else:
            text += f"{prefix}▸ {key.replace('_', ' ').title()}: `{value}`\n"
    
    return text.strip() or "No data found"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ **Bot Online!**\n\n"
        "📌 **Commands:**\n"
        "▸ `/ip <IP>` - Get IP details\n"
        "▸ `/ifsc <IFSC>` - Get IFSC bank details\n"
        "▸ `/ifscadv <IFSC>` - Get advanced IFSC details\n\n"
        "🔹 **Example:** `/ip 8.8.8.8`",
        parse_mode="Markdown"
    )

async def ipinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        return await update.message.reply_text("❌ **Usage:** `/ip <IP_ADDRESS>`", parse_mode="Markdown")
    
    ip = context.args[0]
    await update.message.reply_text(f"⏳ Fetching details for `{ip}`...", parse_mode="Markdown")
    
    try:
        r = requests.get(f"{BASE_URL}/ipinfo?token={API_TOKEN}&ip={ip}", timeout=15)
        r.raise_for_status()
        data = r.json()
        
        if "response" in data and "data" in data["response"]:
            formatted = format_response(data["response"]["data"])
        else:
            formatted = format_response(data)
            
        await update.message.reply_text(f"🌐 **IP Details:** `{ip}`\n\n{formatted}", parse_mode="Markdown")
    except requests.exceptions.Timeout:
        await update.message.reply_text("❌ **Timeout:** API not responding", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ **Error:** `{str(e)}`", parse_mode="Markdown")

async def ifsc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        return await update.message.reply_text("❌ **Usage:** `/ifsc <IFSC_CODE>`", parse_mode="Markdown")
    
    code = context.args[0].upper()
    await update.message.reply_text(f"⏳ Fetching IFSC details for `{code}`...", parse_mode="Markdown")
    
    try:
        r = requests.get(f"{BASE_URL}/ifsc-razor?token={API_TOKEN}&ifsc={code}", timeout=15)
        r.raise_for_status()
        data = r.json()
        formatted = format_response(data)
        await update.message.reply_text(f"🏦 **IFSC Details:** `{code}`\n\n{formatted}", parse_mode="Markdown")
    except requests.exceptions.Timeout:
        await update.message.reply_text("❌ **Timeout:** API not responding", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ **Error:** `{str(e)}`", parse_mode="Markdown")

async def ifscadv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        return await update.message.reply_text("❌ **Usage:** `/ifscadv <IFSC_CODE>`", parse_mode="Markdown")
    
    code = context.args[0].upper()
    await update.message.reply_text(f"⏳ Fetching advanced IFSC details for `{code}`...", parse_mode="Markdown")
    
    try:
        r = requests.get(f"{BASE_URL}/ifsc-adv?token={API_TOKEN}&ifsc={code}", timeout=15)
        r.raise_for_status()
        data = r.json()
        formatted = format_response(data)
        await update.message.reply_text(f"🏦 **Advanced IFSC Details:** `{code}`\n\n{formatted}", parse_mode="Markdown")
    except requests.exceptions.Timeout:
        await update.message.reply_text("❌ **Timeout:** API not responding", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ **Error:** `{str(e)}`", parse_mode="Markdown")

def setup_bot():
    """Setup and run Telegram bot in background thread"""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set!")
        return
    
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("ip", ipinfo))
    application.add_handler(CommandHandler("ifsc", ifsc))
    application.add_handler(CommandHandler("ifscadv", ifscadv))
    
    logger.info("🤖 Bot is running...")
    application.run_polling()

@app.route('/')
def home():
    return "✅ Bot is running! Visit https://t.me/your_bot_username to use."

@app.route('/health')
def health():
    return {"status": "ok", "message": "Bot is active"}

if __name__ == "__main__":
    # Start bot in background thread
    bot_thread = threading.Thread(target=setup_bot, daemon=True)
    bot_thread.start()
    
    # Run Flask web server
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)