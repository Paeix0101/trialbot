import os
import json
import logging
import threading
import time
import requests
import asyncio

from flask import Flask, request
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --------------------- CONFIG ---------------------
TOKEN = os.getenv("BOT_TOKEN")
API_TOKEN = os.getenv("API_TOKEN") or "xpol_Randi_53f66910"
OWNER_ID = int(os.getenv("OWNER_ID") or 7735508963)
BASE_URL = "https://xpolitesupgrade-api.darrify-api.workers.dev/api"

# Webhook URL - Render automatically provides RENDER_EXTERNAL_HOSTNAME
RENDER_HOST = os.getenv("RENDER_EXTERNAL_HOSTNAME")
if RENDER_HOST:
    WEBHOOK_URL = f"https://{RENDER_HOST}/{TOKEN}"
else:
    # Fallback - aapko manually dalna hoga
    WEBHOOK_URL = f"https://trialbot-d27t.onrender.com/{TOKEN}"

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

# --------------------- Handlers ---------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ **Bot Online!**\n\n"
        "📌 **Commands:**\n"
        "▸ `/ip <IP>` - Get IP details\n"
        "▸ `/ifsc <IFSC>` - Get IFSC bank details\n"
        "▸ `/ifscadv <IFSC>` - Get advanced IFSC details\n\n"
        "🔹 **Example:** `/ip 8.8.8.8`\n\n"
        f"🔗 Webhook: `{WEBHOOK_URL}`",
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
    text = update.message.text
    if text and text.startswith('+'):
        await update.message.reply_text("📱 **Phone number received!**\n\nUse `/ip <IP>` or `/ifsc <IFSC>` commands.", parse_mode="Markdown")
    else:
        await update.message.reply_text("Send /start for commands list...")

# --------------------- Application Setup ---------------------
def create_application():
    """Create and configure the application"""
    application = Application.builder().token(TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("ip", ipinfo))
    application.add_handler(CommandHandler("ifsc", ifsc))
    application.add_handler(CommandHandler("ifscadv", ifscadv))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))
    
    return application

# Global application instance
application = create_application()

# --------------------- Webhook Setup with Retry ---------------------
def set_webhook_with_retry(max_retries=5, delay=5):
    """Set webhook with retry mechanism"""
    logger.info(f"🔄 Setting webhook: {WEBHOOK_URL}")
    
    for attempt in range(max_retries):
        try:
            # Check current webhook
            current = bot.get_webhook_info()
            logger.info(f"Current webhook: {current.url}")
            
            if current.url == WEBHOOK_URL:
                logger.info("✅ Webhook already set correctly!")
                return True
            
            # Set webhook with longer timeout
            bot.set_webhook(
                url=WEBHOOK_URL,
                timeout=30,
                drop_pending_updates=False
            )
            
            # Verify
            time.sleep(2)
            new_info = bot.get_webhook_info()
            if new_info.url == WEBHOOK_URL:
                logger.info(f"✅ Webhook set successfully! (Attempt {attempt + 1})")
                return True
            else:
                logger.warning(f"Webhook verification failed. Expected: {WEBHOOK_URL}, Got: {new_info.url}")
                
        except Exception as e:
            logger.error(f"Attempt {attempt + 1} failed: {str(e)}")
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {delay} seconds...")
                time.sleep(delay)
            else:
                logger.error("❌ All webhook setting attempts failed!")
                return False
    
    return False

# --------------------- Flask Routes ---------------------
@app.route('/' + TOKEN, methods=['POST'])
def webhook():
    """Handle incoming updates"""
    try:
        # Get update data
        update_data = request.get_json(force=True)
        logger.info("📩 Webhook received update")
        
        # Process update
        update = Update.de_json(update_data, bot)
        application.process_update(update)
        
        return '', 200
    except Exception as e:
        logger.error(f"Webhook processing error: {str(e)}")
        return '', 500

@app.route('/')
def home():
    return "✅ Bot is running with Webhook!"

@app.route('/health')
def health():
    try:
        info = bot.get_webhook_info()
        return {
            "status": "ok",
            "webhook_url": info.url,
            "pending_updates": info.pending_update_count,
            "last_error": info.last_error_message,
            "last_error_date": info.last_error_date
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.route('/setwebhook')
def set_webhook_route():
    """Manually trigger webhook setup"""
    success = set_webhook_with_retry()
    if success:
        return {"status": "ok", "message": "Webhook set successfully!", "url": WEBHOOK_URL}
    else:
        return {"status": "error", "message": "Failed to set webhook"}

# --------------------- Keep Alive ---------------------
def keep_alive():
    """Keep the service alive"""
    while True:
        try:
            home_url = f"https://{RENDER_HOST}" if RENDER_HOST else "https://trialbot-d27t.onrender.com"
            requests.get(home_url, timeout=5)
            logger.info("🔄 Keep-alive ping sent.")
        except Exception as e:
            logger.error(f"Keep-alive failed: {e}")
        time.sleep(300)  # 5 minutes

# --------------------- Main ---------------------
if __name__ == '__main__':
    logger.info("🚀 Starting application...")
    logger.info(f"📌 Webhook URL: {WEBHOOK_URL}")
    logger.info(f"🤖 Bot Token: {TOKEN[:10]}...")
    
    # Set webhook
    success = set_webhook_with_retry(max_retries=5, delay=3)
    
    if not success:
        logger.warning("⚠️ Webhook setup failed! You can manually set it using:")
        logger.warning(f"   https://api.telegram.org/bot{TOKEN}/setWebhook?url={WEBHOOK_URL}")
        logger.warning("   Or visit: /setwebhook route")
    
    # Start keep-alive thread
    threading.Thread(target=keep_alive, daemon=True).start()
    logger.info("🔄 Keep-alive thread started")
    
    # Run Flask
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🌐 Starting Flask server on port {port}")
    app.run(host='0.0.0.0', port=port)