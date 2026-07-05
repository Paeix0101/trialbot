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
TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = 7735508963
USERS_FILE = "users.txt"
WELCOME_FILE = "welcome.json"
API_TOKEN = "xpol_Randi_53f66910"

WEBHOOK_URL = f"https://gbbot-s267.onrender.com/{TOKEN}"
# --------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
bot = Bot(token=TOKEN)
dispatcher = Dispatcher(bot, None, use_context=True)

lock = threading.Lock()

# ---------- API Functions ----------
def get_ifsc_info(ifsc_code):
    results = {}
    try:
        url1 = f"https://xpolitesupgrade-api.darrify-api.workers.dev/api/ifsc-adv?token={API_TOKEN}&ifsc={ifsc_code}"
        response = requests.get(url1, timeout=10)
        if response.status_code == 200:
            results['adv'] = response.json()
    except:
        pass
    
    try:
        url2 = f"https://xpolitesupgrade-api.darrify-api.workers.dev/api/ifsc-razor?token={API_TOKEN}&ifsc={ifsc_code}"
        response = requests.get(url2, timeout=10)
        if response.status_code == 200:
            results['razor'] = response.json()
    except:
        pass
    return results

def get_ip_info(ip_address):
    try:
        url = f"https://xpolitesupgrade-api.darrify-api.workers.dev/api/ipinfo?token={API_TOKEN}&ip={ip_address}"
        response = requests.get(url, timeout=10)
        return response.json() if response.status_code == 200 else {"error": "Failed"}
    except:
        return {"error": "API Error"}

def get_upi_info(upi_id):
    """New: UPI ID se bank details nikalne ke liye"""
    try:
        # Try possible UPI endpoints
        endpoints = [
            f"https://xpolitesupgrade-api.darrify-api.workers.dev/api/upi?token={API_TOKEN}&upi={upi_id}",
            f"https://xpolitesupgrade-api.darrify-api.workers.dev/api/upicheck?token={API_TOKEN}&upi={upi_id}",
            f"https://xpolitesupgrade-api.darrify-api.workers.dev/api/vpa?token={API_TOKEN}&vpa={upi_id}",
            f"https://xpolitesupgrade-api.darrify-api.workers.dev/api/upiinfo?token={API_TOKEN}&upi={upi_id}"
        ]
        
        for url in endpoints:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data and not data.get("error"):
                    return data
        return {"error": "UPI details not found or API not supported"}
    except Exception as e:
        return {"error": str(e)}

def format_response(data, title):
    if not data or isinstance(data, dict) and "error" in data:
        return f"⚠️ {title} Error: {data.get('error', 'No data')}"
    
    formatted = [f"📊 **{title} Details:**"]
    for key, value in data.items():
        if value and value not in ["null", None, "", {}, []]:
            formatted.append(f"• {key.replace('_', ' ').title()}: {value}")
    return "\n".join(formatted)

# ---------- Load/Save Functions (same) ----------
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
    except:
        pass

# ---------- Detection Functions ----------
def detect_ifsc(text):
    pattern = r'\b[A-Z]{4}0[A-Z0-9]{6}\b'
    match = re.search(pattern, text)
    return match.group(0) if match else None

def detect_phone(text):
    cleaned = re.sub(r'[\s\-\(\)\+]', '', text)
    pattern = r'\b[0-9]{10}\b'
    match = re.search(pattern, cleaned)
    return match.group(0) if match else None

def detect_upi(text):
    pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    match = re.search(pattern, text)
    return match.group(0) if match else None

def detect_ip(text):
    pattern = r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'
    match = re.search(pattern, text)
    return match.group(0) if match else None

# ---------- Process Message ----------
def process_message(text, user_id):
    # IFSC
    ifsc = detect_ifsc(text)
    if ifsc:
        response = f"🔍 **Detected IFSC:** `{ifsc}`\n\n"
        data = get_ifsc_info(ifsc)
        return response + format_response(data, "IFSC")

    # IP
    ip = detect_ip(text)
    if ip:
        response = f"🌐 **Detected IP:** `{ip}`\n\n"
        data = get_ip_info(ip)
        return response + format_response(data, "IP")

    # UPI ID (New)
    upi = detect_upi(text)
    if upi:
        response = f"💳 **Detected UPI ID:** `{upi}`\n\n"
        data = get_upi_info(upi)
        return response + format_response(data, "UPI Bank")

    # Phone Number
    phone = detect_phone(text)
    if phone:
        return f"📱 **Phone Number Detected:** `{phone}`\n\nℹ️ Currently only IFSC, UPI & IP supported."

    return None

# ---------- Handlers (same) ----------
def start(update: Update, context: CallbackContext):
    user = update.effective_user
    save_user(user.id)
    forward_id(user.id)
    text = welcome_data["text"]
    photo = welcome_data["photo"]
    if photo:
        bot.send_photo(chat_id=user.id, photo=photo, caption=text)
    else:
        bot.send_message(chat_id=user.id, text=text)

def any_message(update: Update, context: CallbackContext):
    user = update.effective_user
    save_user(user.id)
    forward_id(user.id)
    
    text = update.message.text or ""
    response = process_message(text, user.id)
    
    if response:
        update.message.reply_text(response, parse_mode='Markdown')
    else:
        update.message.reply_text(
            "🤖 **Main yeh support karta hu:**\n"
            "• IFSC Code\n"
            "• UPI ID (Bank details)\n"
            "• IP Address\n"
            "• Phone Number (detect only)\n\n"
            "Kuch bhi bhej ke try karo!", 
            parse_mode='Markdown'
        )

# Other handlers same rakhe hain (gbupdate, gbboardcaste)
def gbupdate(update: Update, context: CallbackContext):
    # ... (same as before)
    msg = update.message.reply_to_message
    if not msg: return
    text = msg.caption or msg.text or ""
    photo = msg.photo[-1].file_id if msg.photo else (msg.document.file_id if msg.document else None)
    save_welcome(text, photo)
    global welcome_data
    welcome_data = load_welcome()
    update.message.reply_text("✅ Welcome message updated!")

def gbboardcaste(update: Update, context: CallbackContext):
    # ... (same as before)
    msg = update.message.reply_to_message
    if not msg: return
    users = load_users()
    text = msg.caption or msg.text or ""
    photo = msg.photo[-1].file_id if msg.photo else (msg.document.file_id if msg.document else None)
    for uid in users:
        try:
            if photo:
                bot.send_photo(chat_id=uid, photo=photo, caption=text)
            else:
                bot.send_message(chat_id=uid, text=text)
        except:
            pass

# Register handlers
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("gbupdate", gbupdate))
dispatcher.add_handler(CommandHandler("gbboardcaste", gbboardcaste))
dispatcher.add_handler(MessageHandler(Filters.all & ~Filters.command, any_message))

# Webhook routes (same)
@app.route('/' + TOKEN, methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return '', 200

@app.route('/')
def index():
    return 'Bot is alive! ✅'

def set_webhook():
    if bot.get_webhook_info().url != WEBHOOK_URL:
        bot.set_webhook(url=WEBHOOK_URL)
        logger.info(f"Webhook set to {WEBHOOK_URL}")

def keep_alive():
    while True:
        try:
            requests.get(WEBHOOK_URL)
        except:
            pass
        time.sleep(300)

if __name__ == '__main__':
    set_webhook()
    threading.Thread(target=keep_alive, daemon=True).start()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)