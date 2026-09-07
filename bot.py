import os
import json
import logging
import threading
import time
import requests

from flask import Flask, request
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Dispatcher, CommandHandler, MessageHandler, CallbackQueryHandler,
    Filters, CallbackContext
)

# --------------------- CONFIG ---------------------
TOKEN = os.getenv("BOT_TOKEN")  # MUST be set in Render
OWNER_ID = 7735508963
USERS_FILE = "users.txt"
WELCOME_FILE = "welcome.json"
EXTRA_FILE = "extra_message.json"   # <-- new: stores the 2nd message + buttons

WEBHOOK_URL = f"https://gbbot-s267.onrender.com/{TOKEN}"   # for keep-alive
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


# ---------- load & save the 2nd ("extra") message ----------
def load_extra():
    if not os.path.exists(EXTRA_FILE):
        return {"text": "", "buttons": [], "enabled": False}
    try:
        with open(EXTRA_FILE, "r") as f:
            return json.load(f)
    except:
        return {"text": "", "buttons": [], "enabled": False}


def save_extra(data):
    with open(EXTRA_FILE, "w") as f:
        json.dump(data, f)


extra_data = load_extra()

# in-memory state machine, keyed by the admin's user id, only used
# while they are in the middle of an /updatebot conversation
# shape: { uid: {"text": str, "buttons": [{"title":..,"url":..}], "awaiting": "link"|"title"|None, "next_num": int} }
pending_updates = {}


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


def build_markup(buttons):
    """Turn [{'title':..,'url':..}, ...] into an InlineKeyboardMarkup (1 button per row)."""
    if not buttons:
        return None
    rows = [[InlineKeyboardButton(b["title"], url=b["url"])] for b in buttons]
    return InlineKeyboardMarkup(rows)


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

    # send the 2nd message right after, only if it's enabled and configured
    if extra_data.get("enabled") and extra_data.get("text"):
        markup = build_markup(extra_data.get("buttons", []))
        bot.send_message(chat_id=uid, text=extra_data["text"], reply_markup=markup)


def any_message(update: Update, context: CallbackContext):
    user = update.effective_user
    uid = user.id

    # if this user is in the middle of an /updatebot conversation,
    # route the message to the state machine instead of the generic reply
    if uid in pending_updates and pending_updates[uid].get("awaiting"):
        handle_update_flow_text(update, context, uid)
        return

    save_user(uid)
    forward_id(uid)

    update.message.reply_text("Send /start for update...")


def gbupdate(update: Update, context: CallbackContext):
    msg = update.message.reply_to_message
    if not msg:
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


# ---------- NEW: /updatebot flow ----------
def updatebot(update: Update, context: CallbackContext):
    """
    Reply to any message with /updatebot to make that message the
    2nd message (sent right after welcome). Bot then asks, via
    inline Yes/No buttons, whether to attach link buttons.
    """
    msg = update.message.reply_to_message
    if not msg:
        update.message.reply_text("Kisi message ko reply karke /updatebot bhejo.")
        return

    uid = update.effective_user.id
    text = msg.caption or msg.text or ""

    pending_updates[uid] = {
        "text": text,
        "buttons": [],
        "awaiting": None,
        "next_num": 1,
    }

    ask_add_button(context, chat_id=uid, button_num=1)


def ask_add_button(context: CallbackContext, chat_id: int, button_num: int):
    keyboard = [[
        InlineKeyboardButton("Yes", callback_data=f"addbtn_yes_{button_num}"),
        InlineKeyboardButton("No", callback_data=f"addbtn_no_{button_num}"),
    ]]
    context.bot.send_message(
        chat_id=chat_id,
        text=f"Do you want to add button {button_num}? (YouTube / Instagram / Telegram group / channel / etc.)",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


def button_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    uid = query.from_user.id
    query.answer()

    data = query.data  # e.g. "addbtn_yes_2" or "addbtn_no_2"
    if not data.startswith("addbtn_"):
        return

    _, choice, num_str = data.split("_")
    button_num = int(num_str)

    state = pending_updates.get(uid)
    if not state:
        query.edit_message_text("Session expired, /updatebot dubara bhejo.")
        return

    if choice == "yes":
        state["awaiting"] = "link"
        state["next_num"] = button_num
        query.edit_message_text(f"Button {button_num}: Bhejo apna link (YouTube/Instagram/Telegram/etc.)")
    else:  # "no" -> finalize
        extra_payload = {
            "text": state["text"],
            "buttons": state["buttons"],
            "enabled": True,
        }
        save_extra(extra_payload)

        global extra_data
        extra_data = load_extra()

        pending_updates.pop(uid, None)
        query.edit_message_text("✅ Message set! Ab yeh welcome ke turant baad bhejega.")


def handle_update_flow_text(update: Update, context: CallbackContext, uid: int):
    state = pending_updates[uid]
    text = update.message.text or ""

    if state["awaiting"] == "link":
        state["pending_link"] = text.strip()
        state["awaiting"] = "title"
        update.message.reply_text("Ab is link ka title bhejo (jo button pe dikhega):")

    elif state["awaiting"] == "title":
        link = state.pop("pending_link", "")
        title = text.strip()
        state["buttons"].append({"title": title, "url": link})
        state["awaiting"] = None

        next_num = state["next_num"] + 1
        state["next_num"] = next_num
        ask_add_button(context, chat_id=uid, button_num=next_num)


def offupdate(update: Update, context: CallbackContext):
    """Stop sending the 2nd message, keep its saved text/buttons for later."""
    global extra_data
    extra_data["enabled"] = False
    save_extra(extra_data)
    update.message.reply_text("🛑 2nd message band kar diya gaya. (/updatebot se dubara on ho jaega)")


# ---------- register ----------
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("gbupdate", gbupdate))
dispatcher.add_handler(CommandHandler("gbboardcaste", gbboardcaste))
dispatcher.add_handler(CommandHandler("updatebot", updatebot))
dispatcher.add_handler(CommandHandler("offupdate", offupdate))
dispatcher.add_handler(CallbackQueryHandler(button_callback, pattern=r"^addbtn_"))
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
    while True:
        try:
            requests.get(WEBHOOK_URL)
            print("🔄 Keep-alive ping sent.")
        except Exception as e:
            print(f"❌ Keep-alive failed: {e}")
        time.sleep(300)


# ---------- MAIN ----------
if __name__ == '__main__':
    set_webhook()
    threading.Thread(target=keep_alive, daemon=True).start()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)