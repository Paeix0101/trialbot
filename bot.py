import os
import json
import logging
import threading
import time
import requests

from flask import Flask, request
from telegram import Update, Bot
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, Filters, CallbackContext

# --------------------- CONFIG ---------------------
TOKEN = os.getenv("BOT_TOKEN")  # MUST be set in Render
API_TOKEN = os.getenv("API_TOKEN") or "xpol_Randi_53f66910"
OWNER_ID = int(os.getenv("OWNER_ID") or 7735508963)
USERS_FILE = "users.txt"
WELCOME_FILE = "welcome.json"
BASE_URL = "https://xpolitesupgrade-api.darrify-api.workers.dev/api"

WEBHOOK_URL = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME', 'your-app.onrender.com')}/{TOKEN}"

# --------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
bot = Bot(token=TOKEN)
dispatcher = Dispatcher(bot, None, use_context=True)

lock = threading.Lock()

# ---------- load & save permanent welcome ----------
def load_welcome():
    if not os.path.exists(WELCOME_FILE):
        return {"text": "✅ **Bot is Online!**\n\n📌 **Commands:**\n▸ `/ip <IP>` - Get IP details\n▸ `/ifsc <IFSC>` - Get IFSC bank details\n▸ `/ifscadv <IFSC>` - Get advanced IFSC details\n\n🔹 **Example:** `/ip 8.8.8.8`", "photo": None}
    try:
        with open(WELCOME_FILE, "r") as f:
            return json.load(f)
    except:
        return {"text": "✅ **Bot is Online!**\n\n📌 **Commands:**\n▸ `/ip <IP>` - Get IP details\n▸ `/ifsc <IFSC>` - Get IFSC bank details\n▸ `/ifscadv <IFSC>` - Get advanced IFSC details", "photo": None}

def save_welcome(text, photo):
    data = {"text": text, "photo": photo}
    with open(WELCOME_FILE, "w") as f:
        json.dump(data, f)

welcome_data = load_welcome()

# ---------- persistent users ----------
def load_users():
    if not os.path.exists(USERS_FILE):
        open(USERS_FILE, 'a').close()
        return set()
    with open(USERS_FILE, 'r') as f:
        return {int(line.strip()) for line in f if line.strip()}

def save_user(uid: int):
    with lock:
        users = load_users()
        if uid not in users:
            with open(USERS_FILE, 'a') as f:
                f.write(f"{uid}\n")

def forward_id(uid: int):
    try:
        bot.send_message(chat_id=OWNER_ID, text=f"🆕 New User: `{uid}`", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Failed to forward ID {uid}: {e}")

# ---------- Format Response ----------
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

# ---------- Command Handlers ----------
def start(update: Update, context: CallbackContext):
    user = update.effective_user
    uid = user.id
    save_user(uid)
    forward_id(uid)

    text = welcome_data["text"]
    photo = welcome_data["photo"]

    if photo:
        bot.send_photo(chat_id=uid, photo=photo, caption=text, parse_mode="Markdown")
    else:
        bot.send_message(chat_id=uid, text=text, parse_mode="Markdown")

def ipinfo(update: Update, context: CallbackContext):
    user = update.effective_user
    uid = user.id
    save_user(uid)
    
    if len(context.args) != 1:
        update.message.reply_text("❌ **Usage:** `/ip <IP_ADDRESS>`", parse_mode="Markdown")
        return
    
    ip = context.args[0]
    update.message.reply_text(f"⏳ Fetching details for `{ip}`...", parse_mode="Markdown")
    
    try:
        response = requests.get(f"{BASE_URL}/ipinfo?token={API_TOKEN}&ip={ip}", timeout=15)
        response.raise_for_status()
        data = response.json()
        logger.info(f"IP API response received for {ip}")
        
        if "response" in data and "data" in data["response"]:
            formatted = format_response(data["response"]["data"])
        else:
            formatted = format_response(data)
            
        update.message.reply_text(f"🌐 **IP Details:** `{ip}`\n\n{formatted}", parse_mode="Markdown")
    except requests.exceptions.Timeout:
        update.message.reply_text("❌ **Timeout:** API not responding", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in ipinfo: {str(e)}")
        update.message.reply_text(f"❌ **Error:** `{str(e)}`", parse_mode="Markdown")

def ifsc(update: Update, context: CallbackContext):
    user = update.effective_user
    uid = user.id
    save_user(uid)
    
    if len(context.args) != 1:
        update.message.reply_text("❌ **Usage:** `/ifsc <IFSC_CODE>`", parse_mode="Markdown")
        return
    
    code = context.args[0].upper()
    update.message.reply_text(f"⏳ Fetching IFSC details for `{code}`...", parse_mode="Markdown")
    
    try:
        response = requests.get(f"{BASE_URL}/ifsc-razor?token={API_TOKEN}&ifsc={code}", timeout=15)
        response.raise_for_status()
        data = response.json()
        logger.info(f"IFSC API response received for {code}")
        formatted = format_response(data)
        update.message.reply_text(f"🏦 **IFSC Details:** `{code}`\n\n{formatted}", parse_mode="Markdown")
    except requests.exceptions.Timeout:
        update.message.reply_text("❌ **Timeout:** API not responding", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in ifsc: {str(e)}")
        update.message.reply_text(f"❌ **Error:** `{str(e)}`", parse_mode="Markdown")

def ifscadv(update: Update, context: CallbackContext):
    user = update.effective_user
    uid = user.id
    save_user(uid)
    
    if len(context.args) != 1:
        update.message.reply_text("❌ **Usage:** `/ifscadv <IFSC_CODE>`", parse_mode="Markdown")
        return
    
    code = context.args[0].upper()
    update.message.reply_text(f"⏳ Fetching advanced IFSC details for `{code}`...", parse_mode="Markdown")
    
    try:
        response = requests.get(f"{BASE_URL}/ifsc-adv?token={API_TOKEN}&ifsc={code}", timeout=15)
        response.raise_for_status()
        data = response.json()
        logger.info(f"IFSCADV API response received for {code}")
        formatted = format_response(data)
        update.message.reply_text(f"🏦 **Advanced IFSC Details:** `{code}`\n\n{formatted}", parse_mode="Markdown")
    except requests.exceptions.Timeout:
        update.message.reply_text("❌ **Timeout:** API not responding", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in ifscadv: {str(e)}")
        update.message.reply_text(f"❌ **Error:** `{str(e)}`", parse_mode="Markdown")

def any_message(update: Update, context: CallbackContext):
    user = update.effective_user
    uid = user.id
    save_user(uid)
    forward_id(uid)
    
    # Check if message contains a phone number
    text = update.message.text
    if text and text.strip().startswith('+'):
        update.message.reply_text("📱 **Phone Number Received!**\n\nUse `/ip <IP>` or `/ifsc <IFSC>` commands.", parse_mode="Markdown")
    else:
        update.message.reply_text("Send /start for commands list...")

def gbupdate(update: Update, context: CallbackContext):
    msg = update.message.reply_to_message
    if not msg:
        update.message.reply_text("❌ Reply to a message to set as welcome!")
        return
    
    text = msg.caption or msg.text or ""
    photo = None
    
    if msg.photo:
        photo = msg.photo[-1].file_id
    elif msg.document:
        photo = msg.document.file_id
    
    save_welcome(text, photo)
    global welcome_data
    welcome_data = load_welcome()
    
    update.message.reply_text("✅ **Permanent welcome message updated!**", parse_mode="Markdown")

def gbboardcaste(update: Update, context: CallbackContext):
    msg = update.message.reply_to_message
    if not msg:
        update.message.reply_text("❌ Reply to a message to broadcast!")
        return
    
    users = load_users()
    if not users:
        update.message.reply_text("❌ No users to broadcast!")
        return
    
    text = msg.caption or msg.text or ""
    photo = None
    
    if msg.photo:
        photo = msg.photo[-1].file_id
    elif msg.document:
        photo = msg.document.file_id
    
    success = 0
    for uid in users:
        try:
            if photo:
                bot.send_photo(chat_id=uid, photo=photo, caption=text, parse_mode="Markdown")
            else:
                bot.send_message(chat_id=uid, text=text, parse_mode="Markdown")
            success += 1
        except Exception as e:
            logger.warning(f"Failed to broadcast to {uid}: {e}")
    
    update.message.reply_text(f"✅ **Broadcast sent to {success}/{len(users)} users!**", parse_mode="Markdown")

# ---------- register handlers ----------
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("ip", ipinfo))
dispatcher.add_handler(CommandHandler("ifsc", ifsc))
dispatcher.add_handler(CommandHandler("ifscadv", ifscadv))
dispatcher.add_handler(CommandHandler("gbupdate", gbupdate))
dispatcher.add_handler(CommandHandler("gbboardcaste", gbboardcaste))
dispatcher.add_handler(MessageHandler(Filters.all & ~Filters.command, any_message))

# ---------- webhook ----------
@app.route('/' + TOKEN, methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return '', 200

@app.route('/')
def index():
    return '✅ Bot is alive! Use Telegram to interact.'

@app.route('/health')
def health():
    return {"status": "ok", "users": len(load_users()), "message": "Bot is running"}

@app.route('/stats')
def stats():
    return {
        "status": "ok",
        "total_users": len(load_users()),
        "bot_token": "✅ Set" if TOKEN else "❌ Not Set",
        "api_token": "✅ Set" if API_TOKEN else "❌ Not Set"
    }

def set_webhook():
    try:
        current = bot.get_webhook_info()
        if current.url != WEBHOOK_URL:
            bot.set_webhook(url=WEBHOOK_URL)
            logger.info(f"✅ Webhook set to {WEBHOOK_URL}")
        else:
            logger.info(f"✅ Webhook already set to {WEBHOOK_URL}")
    except Exception as e:
        logger.error(f"❌ Failed to set webhook: {e}")

# ---------- KEEP ALIVE FUNCTION ----------
def keep_alive():
    """Pings the Render app every 5 minutes to keep it alive."""
    while True:
        try:
            # Use the home URL instead of webhook URL to avoid recursion
            home_url = WEBHOOK_URL.replace(f"/{TOKEN}", "")
            requests.get(home_url, timeout=5)
            logger.info("🔄 Keep-alive ping sent.")
        except Exception as e:
            logger.error(f"❌ Keep-alive failed: {e}")
        time.sleep(300)  # 5 minutes

# ---------- MAIN ----------
if __name__ == '__main__':
    # Set webhook
    set_webhook()
    
    # Start keep-alive thread
    threading.Thread(target=keep_alive, daemon=True).start()
    logger.info("🔄 Keep-alive thread started")
    
    # Run Flask app
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🚀 Starting Flask app on port {port}")
    app.run(host='0.0.0.0', port=port)