import os
import logging
import requests
import json

from flask import Flask, request, jsonify
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --------------------- CONFIG ---------------------
TOKEN = os.getenv("BOT_TOKEN")
API_TOKEN = os.getenv("API_TOKEN") or "xpol_Randi_53f66910"
BASE_URL = "https://xpolitesupgrade-api.darrify-api.workers.dev/api"

# Webhook URL - Render automatically provides RENDER_EXTERNAL_HOSTNAME
RENDER_HOST = os.getenv("RENDER_EXTERNAL_HOSTNAME", "trialbot-d27t.onrender.com")
WEBHOOK_URL = f"https://{RENDER_HOST}/{TOKEN}"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
bot = Bot(token=TOKEN)

# --------------------- Format Response ---------------------
def format_response(data, indent=0):
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

# --------------------- Command Handlers ---------------------
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
        await update.message.reply_text("❌ **Usage:** `/ip <IP_ADDRESS>`", parse_mode="Markdown")
        return
    
    ip = context.args[0]
    await update.message.reply_text(f"⏳ Fetching details for `{ip}`...", parse_mode="Markdown")
    
    try:
        response = requests.get(f"{BASE_URL}/ipinfo?token={API_TOKEN}&ip={ip}", timeout=15)
        response.raise_for_status()
        data = response.json()
        
        if "response" in data and "data" in data["response"]:
            formatted = format_response(data["response"]["data"])
        else:
            formatted = format_response(data)
            
        await update.message.reply_text(f"🌐 **IP Details:** `{ip}`\n\n{formatted}", parse_mode="Markdown")
    except requests.exceptions.Timeout:
        await update.message.reply_text("❌ **Timeout:** API not responding", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in ipinfo: {str(e)}")
        await update.message.reply_text(f"❌ **Error:** `{str(e)}`", parse_mode="Markdown")

async def ifsc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("❌ **Usage:** `/ifsc <IFSC_CODE>`", parse_mode="Markdown")
        return
    
    code = context.args[0].upper()
    await update.message.reply_text(f"⏳ Fetching IFSC details for `{code}`...", parse_mode="Markdown")
    
    try:
        response = requests.get(f"{BASE_URL}/ifsc-razor?token={API_TOKEN}&ifsc={code}", timeout=15)
        response.raise_for_status()
        data = response.json()
        formatted = format_response(data)
        await update.message.reply_text(f"🏦 **IFSC Details:** `{code}`\n\n{formatted}", parse_mode="Markdown")
    except requests.exceptions.Timeout:
        await update.message.reply_text("❌ **Timeout:** API not responding", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in ifsc: {str(e)}")
        await update.message.reply_text(f"❌ **Error:** `{str(e)}`", parse_mode="Markdown")

async def ifscadv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("❌ **Usage:** `/ifscadv <IFSC_CODE>`", parse_mode="Markdown")
        return
    
    code = context.args[0].upper()
    await update.message.reply_text(f"⏳ Fetching advanced IFSC details for `{code}`...", parse_mode="Markdown")
    
    try:
        response = requests.get(f"{BASE_URL}/ifsc-adv?token={API_TOKEN}&ifsc={code}", timeout=15)
        response.raise_for_status()
        data = response.json()
        formatted = format_response(data)
        await update.message.reply_text(f"🏦 **Advanced IFSC Details:** `{code}`\n\n{formatted}", parse_mode="Markdown")
    except requests.exceptions.Timeout:
        await update.message.reply_text("❌ **Timeout:** API not responding", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in ifscadv: {str(e)}")
        await update.message.reply_text(f"❌ **Error:** `{str(e)}`", parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle any non-command message"""
    text = update.message.text
    if text and text.startswith('+'):
        await update.message.reply_text("📱 **Phone number received!**\n\nUse `/ip <IP>` or `/ifsc <IFSC>` commands.", parse_mode="Markdown")
    else:
        await update.message.reply_text("Send /start for commands list...")

# --------------------- Application Setup ---------------------
application = Application.builder().token(TOKEN).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("ip", ipinfo))
application.add_handler(CommandHandler("ifsc", ifsc))
application.add_handler(CommandHandler("ifscadv", ifscadv))
application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

# --------------------- Flask Routes ---------------------
@app.route('/' + TOKEN, methods=['POST'])
def webhook():
    """Handle incoming updates from Telegram"""
    try:
        update_data = request.get_json(force=True)
        logger.info(f"📩 Webhook received: {update_data.get('update_id', 'unknown')}")
        update = Update.de_json(update_data, bot)
        application.process_update(update)
        return '', 200
    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        return '', 500

@app.route('/')
def home():
    return "✅ Bot is running with Webhook!"

@app.route('/health')
def health():
    try:
        info = bot.get_webhook_info()
        return jsonify({
            "status": "ok",
            "webhook_url": info.url,
            "pending_updates": info.pending_update_count,
            "last_error": info.last_error_message
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# --------------------- Main ---------------------
if __name__ == '__main__':
    logger.info("🚀 Starting application...")
    logger.info(f"📌 Webhook URL: {WEBHOOK_URL}")
    
    # Set webhook
    try:
        bot.set_webhook(url=WEBHOOK_URL, timeout=30)
        logger.info("✅ Webhook set successfully!")
    except Exception as e:
        logger.error(f"❌ Failed to set webhook: {e}")
        logger.info(f"👉 Manually set: https://api.telegram.org/bot{TOKEN}/setWebhook?url={WEBHOOK_URL}")
    
    # Run Flask
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🌐 Starting Flask server on port {port}")
    app.run(host='0.0.0.0', port=port)