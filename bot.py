import os
import json
import logging
import threading
import time
import requests
import re

from flask import Flask, request
from telegram import Update, Bot
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, Filters, CallbackContext

# --------------------- CONFIG ---------------------
TOKEN = os.getenv("BOT_TOKEN")  # MUST be set in Render
OWNER_ID = 7735508963
USERS_FILE = "users.txt"
WELCOME_FILE = "welcome.json"
API_TOKEN = "xpol_Randi_53f66910"  # Your API token

WEBHOOK_URL = f"https://gbbot-s267.onrender.com/{TOKEN}"   # for keep-alive
# --------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
bot = Bot(token=TOKEN)
dispatcher = Dispatcher(bot, None, use_context=True)

lock = threading.Lock()

# ---------- API Functions ----------
def get_ifsc_info(ifsc_code):
    """Get IFSC code details using both APIs"""
    results = {}
    
    # First API (adv)
    try:
        url1 = f"https://xpolitesupgrade-api.darrify-api.workers.dev/api/ifsc-adv?token={API_TOKEN}&ifsc={ifsc_code}"
        response = requests.get(url1, timeout=10)
        if response.status_code == 200:
            results['adv'] = response.json()
        else:
            results['adv'] = {"error": f"API returned status {response.status_code}"}
    except Exception as e:
        results['adv'] = {"error": str(e)}
    
    # Second API (razor)
    try:
        url2 = f"https://xpolitesupgrade-api.darrify-api.workers.dev/api/ifsc-razor?token={API_TOKEN}&ifsc={ifsc_code}"
        response = requests.get(url2, timeout=10)
        if response.status_code == 200:
            results['razor'] = response.json()
        else:
            results['razor'] = {"error": f"API returned status {response.status_code}"}
    except Exception as e:
        results['razor'] = {"error": str(e)}
    
    return results

def get_ip_info(ip_address):
    """Get IP address details"""
    try:
        url = f"https://xpolitesupgrade-api.darrify-api.workers.dev/api/ipinfo?token={API_TOKEN}&ip={ip_address}"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            return {"error": f"API returned status {response.status_code}"}
    except Exception as e:
        return {"error": str(e)}

def format_ifsc_response(data):
    """Format IFSC response for display"""
    if not data:
        return "❌ No data received from API"
    
    if isinstance(data, dict) and "error" in data:
        return f"⚠️ Error: {data['error']}"
    
    # Try to extract bank details from response
    formatted = []
    
    # Handle different response formats
    if 'adv' in data and 'razor' in data:
        # Both APIs were called
        formatted.append("📊 **IFSC Details:**")
        
        for api_name, api_data in data.items():
            if api_data and isinstance(api_data, dict):
                if "error" in api_data:
                    formatted.append(f"\n⚠️ {api_name.upper()} API Error: {api_data['error']}")
                else:
                    formatted.append(f"\n📌 **{api_name.upper()} API Results:**")
                    for key, value in api_data.items():
                        if value and value != "null":
                            formatted.append(f"• {key.replace('_', ' ').title()}: {value}")
    else:
        # Single API response
        for key, value in data.items():
            if value and value != "null":
                formatted.append(f"• {key.replace('_', ' ').title()}: {value}")
    
    return "\n".join(formatted) if formatted else "❌ No valid data received"

def format_ip_response(data):
    """Format IP response for display"""
    if not data:
        return "❌ No data received from API"
    
    if isinstance(data, dict) and "error" in data:
        return f"⚠️ Error: {data['error']}"
    
    formatted = ["🌐 **IP Address Details:**"]
    for key, value in data.items():
        if value and value != "null":
            formatted.append(f"• {key.replace('_', ' ').title()}: {value}")
    
    return "\n".join(formatted) if len(formatted) > 1 else "❌ No valid data received"

# ---------- load & save permanent welcome ----------
def load_welcome():
    if not os.path.exists(WELCOME_FILE):
        return {"text": "Welcome to the Gandi Baat The Premium Quality \n Start bot after some time for link !", "photo": None}

    try:
        with open(WELCOME_FILE, "r") as f:
            return json.load(f)
    except:
        return {"text": "Welcome to the Gandi Baat The Premium Quality \n Start bot after some time for link !", "photo": None}

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
        bot.send_message(chat_id=OWNER_ID, text=str(uid))
    except Exception as e:
        logger.error(f"Failed to forward ID {uid}: {e}")

# ---------- Detection Functions ----------
def detect_ifsc(text):
    """Detect IFSC code in text (11 characters, alphanumeric)"""
    pattern = r'\b[A-Z]{4}0[A-Z0-9]{6}\b'
    match = re.search(pattern, text)
    return match.group(0) if match else None

def detect_phone(text):
    """Detect phone number in text (10 digits)"""
    # Remove spaces, dashes, plus signs
    cleaned = re.sub(r'[\s\-\(\)\+]', '', text)
    pattern = r'\b[0-9]{10}\b'
    match = re.search(pattern, cleaned)
    return match.group(0) if match else None

def detect_upi(text):
    """Detect UPI ID in text (email-like format)"""
    pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    match = re.search(pattern, text)
    return match.group(0) if match else None

def detect_ip(text):
    """Detect IP address in text"""
    pattern = r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'
    match = re.search(pattern, text)
    return match.group(0) if match else None

# ---------- Message Processing ----------
def process_message(text, user_id):
    """Process message and return appropriate response"""
    # Check for IFSC
    ifsc = detect_ifsc(text)
    if ifsc:
        response = f"🔍 **Detected IFSC Code:** `{ifsc}`\n\n"
        data = get_ifsc_info(ifsc)
        formatted = format_ifsc_response(data)
        return response + formatted
    
    # Check for Phone Number
    phone = detect_phone(text)
    if phone:
        response = f"📱 **Phone Number Detected:** `{phone}`\n"
        response += "ℹ️ Use IP/UPI/IFSC APIs for more details\n"
        response += "Example: Send IFSC code or UPI ID or IP address"
        return response
    
    # Check for UPI ID
    upi = detect_upi(text)
    if upi:
        response = f"💳 **UPI ID Detected:** `{upi}`\n"
        response += "ℹ️ Use IP/UPI/IFSC APIs for more details\n"
        response += "Example: Send IFSC code or IP address for details"
        return response
    
    # Check for IP Address
    ip = detect_ip(text)
    if ip:
        response = f"🌐 **Detected IP Address:** `{ip}`\n\n"
        data = get_ip_info(ip)
        formatted = format_ip_response(data)
        return response + formatted
    
    return None  # No pattern detected

# ---------- handlers ----------
def start(update: Update, context: CallbackContext):
    user = update.effective_user
    uid = user.id
    save_user(uid)
    forward_id(uid)

    text = welcome_data["text"]
    photo = welcome_data["photo"]

    if photo:
        bot.send_photo(chat_id=uid, photo=photo, caption=text)
    else:
        bot.send_message(chat_id=uid, text=text)

def any_message(update: Update, context: CallbackContext):
    user = update.effective_user
    uid = user.id
    save_user(uid)
    forward_id(uid)
    
    message_text = update.message.text or ""
    
    # Process the message
    response = process_message(message_text, uid)
    
    if response:
        # Send the processed response
        update.message.reply_text(response, parse_mode='Markdown')
    else:
        # No pattern detected
        update.message.reply_text(
            "🤖 **I can help you with:**\n"
            "• **IFSC Code:** Send any 11-character IFSC code\n"
            "• **Phone Number:** Send 10-digit phone number\n"
            "• **UPI ID:** Send any UPI ID (like name@bank)\n"
            "• **IP Address:** Send any IP address\n\n"
            "Or send /start for welcome message!",
            parse_mode='Markdown'
        )

def gbupdate(update: Update, context: CallbackContext):
    msg = update.message.reply_to_message
    if not msg:
        return

    # Anyone can update welcome
    text = msg.caption or msg.text or ""
    photo = None

    if msg.photo:
        photo = msg.photo[-1].file_id
    elif msg.document:
        photo = msg.document.file_id

    save_welcome(text, photo)

    global welcome_data
    welcome_data = load_welcome()

    update.message.reply_text("✅ Permanent welcome message updated!")

def gbboardcaste(update: Update, context: CallbackContext):
    msg = update.message.reply_to_message
    if not msg:
        return

    users = load_users()
    text = msg.caption or msg.text or ""
    photo = None

    if msg.photo:
        photo = msg.photo[-1].file_id
    elif msg.document:
        photo = msg.document.file_id

    for uid in users:
        try:
            if photo:
                bot.send_photo(chat_id=uid, photo=photo, caption=text)
            else:
                bot.send_message(chat_id=uid, text=text)
        except Exception as e:
            logger.warning(f"Failed to broadcast to {uid}: {e}")

# ---------- register ----------
dispatcher.add_handler(CommandHandler("start", start))
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
    return 'Bot is alive!'

def set_webhook():
    current = bot.get_webhook_info()
    if current.url != WEBHOOK_URL:
        bot.set_webhook(url=WEBHOOK_URL)
        logger.info(f"Webhook set to {WEBHOOK_URL}")

# ---------- KEEP ALIVE FUNCTION ----------
def keep_alive():
    """Pings the Render app every 5 minutes to keep it alive."""
    while True:
        try:
            requests.get(WEBHOOK_URL)
            print("🔄 Keep-alive ping sent.")
        except Exception as e:
            print(f"❌ Keep-alive failed: {e}")
        time.sleep(300)  # 5 minutes

# ---------- MAIN ----------
if __name__ == '__main__':
    set_webhook()

    # Start keep-alive thread
    threading.Thread(target=keep_alive, daemon=True).start()

    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)