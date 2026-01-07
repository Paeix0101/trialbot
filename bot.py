import os
import time
import threading
import re
from flask import Flask, request
import requests

TOKEN = os.environ.get("BOT_TOKEN")  # Bot token from BotFather
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")  # e.g. https://your-service.onrender.com (no /webhook)
BOT_API = f"https://api.telegram.org/bot{TOKEN}"

OWNER_ID = 8141547148  # Main Owner with full control

app = Flask(__name__)

repeat_jobs = {}  # {chat_id: [job_ref1, job_ref2, ...]}
groups_file = "groups.txt"
media_groups = {}  # store (chat_id, media_group_id) → (timestamp, list of message_ids)

# Track last one-time broadcast message IDs for deletion
last_broadcast_ids = {}  # {group_id: message_id}

# -------------------- Helper Functions -------------------- #
def send_message(chat_id, text, parse_mode=None):
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    resp = requests.post(f"{BOT_API}/sendMessage", json=payload)
    if resp.status_code == 429:
        print(f"Rate limit hit: {resp.json()}")
    return resp

def delete_message(chat_id, message_id):
    return requests.post(f"{BOT_API}/deleteMessage", json={
        "chat_id": chat_id,
        "message_id": message_id
    })

def get_chat_administrators(chat_id):
    resp = requests.get(f"{BOT_API}/getChatAdministrators", params={"chat_id": chat_id})
    if resp.status_code == 200:
        data = resp.json()
        if data.get("ok"):
            return data["result"]
    return []

def export_invite_link(chat_id):
    resp = requests.get(f"{BOT_API}/exportChatInviteLink", params={"chat_id": chat_id})
    if resp.status_code == 200:
        data = resp.json()
        if data.get("ok"):
            return data.get("result")
    return None

def check_required_permissions(chat_id):
    admins = get_chat_administrators(chat_id)
    bot_info = requests.get(f"{BOT_API}/getMe").json()
    bot_id = bot_info["result"]["id"]
    for admin in admins:
        if admin["user"]["id"] == bot_id:
            perms = (
                admin.get("can_delete_messages", False),
                admin.get("can_restrict_members", False),
                admin.get("can_invite_users", False),
                admin.get("can_promote_members", False)
            )
            return all(perms)
    return False

# --------- REPEATER FUNCTION --------- #
def repeater(chat_id, message_ids, interval, job_ref, is_album=False):
    last_message_ids = []

    while job_ref["running"]:
        # Delete previous repeated messages
        for mid in last_message_ids:
            delete_message(chat_id, mid)
        last_message_ids = []

        try:
            if is_album:
                resp = requests.post(f"{BOT_API}/copyMessages", json={
                    "chat_id": chat_id,
                    "from_chat_id": chat_id,
                    "message_ids": message_ids
                })
                if resp.status_code == 200 and resp.json().get("ok"):
                    last_message_ids = [m["message_id"] for m in resp.json()["result"]]
            else:
                resp = requests.post(f"{BOT_API}/copyMessage", json={
                    "chat_id": chat_id,
                    "from_chat_id": chat_id,
                    "message_id": message_ids[0]
                })
                if resp.status_code == 200 and resp.json().get("ok"):
                    last_message_ids = [resp.json()["result"]["message_id"]]
        except Exception as e:
            print(f"Error in repeater for chat {chat_id}: {e}")

        time.sleep(interval)

# --------- Group Management --------- #
def save_group_id(chat_id):
    if not str(chat_id).startswith("-"):
        return
    if not os.path.exists(groups_file):
        open(groups_file, "w").close()
    with open(groups_file, "r") as f:
        groups = f.read().splitlines()
    if str(chat_id) not in groups:
        with open(groups_file, "a") as f:
            f.write(f"{chat_id}\n")

def load_group_ids():
    if not os.path.exists(groups_file):
        return []
    with open(groups_file, "r") as f:
        return [line.strip() for line in f if line.strip()]

# --------- Broadcast Functions --------- #
def broadcast_message_once(original_chat_id, original_message_id):
    global last_broadcast_ids
    last_broadcast_ids.clear()
    group_ids = load_group_ids()
    success_count = 0
    for gid in group_ids:
        try:
            resp = requests.post(f"{BOT_API}/copyMessage", json={
                "chat_id": int(gid),
                "from_chat_id": original_chat_id,
                "message_id": original_message_id
            })
            if resp.status_code == 200 and resp.json().get("ok"):
                new_msg_id = resp.json()["result"]["message_id"]
                last_broadcast_ids[int(gid)] = new_msg_id
                success_count += 1
        except Exception as e:
            print(f"Failed to broadcast to {gid}: {e}")
    return success_count

def delete_last_broadcast():
    global last_broadcast_ids
    deleted_count = 0
    for gid, mid in list(last_broadcast_ids.items()):
        try:
            delete_message(gid, mid)
            deleted_count += 1
        except Exception as e:
            print(f"Failed to delete in {gid}: {e}")
    last_broadcast_ids.clear()
    return deleted_count

def notify_owner_new_group(chat_id, chat_type, chat_title=""):
    link = export_invite_link(chat_id)
    if chat_type in ["group", "supergroup"]:
        msg = f"📢 Bot added to Group\n<b>{chat_title}</b>\nID: <code>{chat_id}</code>"
    elif chat_type == "channel":
        msg = f"📢 Bot added to Channel\n<b>{chat_title}</b>\nID: <code>{chat_id}</code>"
    else:
        return
    if link:
        msg += f"\n🔗 Invite Link: {link}"
    else:
        msg += "\n⚠️ No invite link (Bot may lack permission)."
    send_message(OWNER_ID, msg, parse_mode="HTML")

def check_bot_status(target_chat_id):
    resp = requests.get(f"{BOT_API}/getChat", params={"chat_id": target_chat_id})
    if not resp.ok or not resp.json().get("ok"):
        return "Bot is inactive (Chat not found or bot removed)."
    admins = get_chat_administrators(target_chat_id)
    bot_info = requests.get(f"{BOT_API}/getMe").json()
    bot_id = bot_info["result"]["id"]
    if any(admin["user"]["id"] == bot_id for admin in admins):
        return "✅ Bot is active (Admin in the group/channel)."
    else:
        return "⚠️ Bot is inactive (Not admin)."

# Cleanup old media groups (optional, prevents memory leak)
def cleanup_media_groups():
    while True:
        time.sleep(600)  # Every 10 minutes
        current_time = time.time()
        to_delete = []
        for key, (ts, _) in media_groups.items():
            if current_time - ts > 600:  # Older than 10 minutes
                to_delete.append(key)
        for key in to_delete:
            del media_groups[key]

threading.Thread(target=cleanup_media_groups, daemon=True).start()

# -------------------- Keep-Alive Function -------------------- #
def keep_alive():
    APP_URL = os.environ.get("APP_URL")  # Set this to your full app URL, e.g. https://your-bot.onrender.com
    if not APP_URL:
        print("APP_URL not set in environment variables. Keep-alive disabled.")
        return
    while True:
        try:
            requests.get(APP_URL, timeout=10)
            print(f"Keep-alive ping sent to {APP_URL}")
        except Exception as e:
            print("Keep-alive ping failed:", e)
        time.sleep(300)  # Ping every 5 minutes (300 seconds)

# Start the keep-alive thread in background
threading.Thread(target=keep_alive, daemon=True).start()

# -------------------- Webhook -------------------- #
@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json()
    msg = update.get("message") or update.get("channel_post")
    my_chat_member = update.get("my_chat_member")

    # Handle bot added/removed or status change
    if my_chat_member:
        chat = my_chat_member["chat"]
        chat_id = chat["id"]
        chat_type = chat["type"]
        chat_title = chat.get("title", "")
        new_status = my_chat_member["new_chat_member"]["status"]

        if new_status in ["administrator", "member"]:
            if not check_required_permissions(chat_id):
                send_message(OWNER_ID, f"❌ Missing required permissions in {chat_title} ({chat_id})")
                return "OK"
            save_group_id(chat_id)
            notify_owner_new_group(chat_id, chat_type, chat_title)
        return "OK"

    if not msg:
        return "OK"

    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or msg.get("caption") or "").strip()
    from_user = msg.get("from", {})
    user_id = from_user.get("id")

    # Save group ID
    if str(chat_id).startswith("-"):
        save_group_id(chat_id)

    # Get admins (for groups)
    admins = [a["user"]["id"] for a in get_chat_administrators(chat_id)] if str(chat_id).startswith("-") else []
    is_admin = user_id in admins if user_id else True

    # Collect media group
    if "media_group_id" in msg:
        mgid = msg["media_group_id"]
        key = (chat_id, mgid)
        if key not in media_groups:
            media_groups[key] = (time.time(), [])
        media_groups[key][1].append(msg["message_id"])

    # === OWNER COMMANDS ===
    if chat_id == OWNER_ID:
        if text.startswith("-") and len(text) > 1:
            status = check_bot_status(text[1:])
            send_message(chat_id, status)
            return "OK"

        if text.lower().startswith("/invitelink"):
            parts = text.split()
            if len(parts) == 2:
                link = export_invite_link(parts[1])
                send_message(chat_id, f"🔗 Invite link:\n{link}" if link else "❌ Failed to get link.")
            else:
                send_message(chat_id, "Usage: /invitelink <group_id>")
            return "OK"

        if text.startswith("/lemonchus") and "reply_to_message" in msg:
            replied = msg["reply_to_message"]
            count = broadcast_message_once(chat_id, replied["message_id"])
            send_message(chat_id, f"✅ Broadcast sent to {count} groups.\nUse /lemonchusstop to delete.")
            return "OK"

        if text.startswith("/lemonchusstop"):
            deleted = delete_last_broadcast()
            send_message(chat_id, f"🗑️ Deleted from {deleted} groups." if deleted else "ℹ️ No broadcast to delete.")
            return "OK"

    # === /start ===
    if text.lower() == "/start":
        start_msg = (
            "🤖 <b>REPEAT MESSAGES BOT</b>\n\n"
            "<b>Dynamic Repeat Feature</b>\n"
            "Now supports any interval in minutes!\n\n"
            "📸 Supports: Text, Images, Videos, Albums (with/without caption)\n"
            "🗑️ Deletes previous message before repeating\n\n"
            "🛠 <b>Commands:</b>\n"
            "🔹 Reply to message + <code>/repeat30minute</code> → every 30 minutes\n"
            "🔹 <code>/repeat1minute</code>, <code>/repeat120minute</code>, etc.\n"
            "🔹 /stop → Stop all repeating\n\n"
            "⚠️ Only <b>admins</b> can use commands."
        )
        send_message(chat_id, start_msg, parse_mode="HTML")
        return "OK"

    # === DYNAMIC REPEAT COMMAND: /repeatXminute ===
    if "reply_to_message" in msg and re.match(r"/repeat\d+minute", text, re.IGNORECASE):
        if not is_admin:
            send_message(chat_id, "❌ Only admins can use this command.")
            return "OK"

        match = re.search(r"(\d+)minute", text, re.IGNORECASE)
        if not match:
            send_message(chat_id, "❌ Invalid format. Use: /repeat30minute")
            return "OK"

        minutes = int(match.group(1))
        if minutes < 1:
            send_message(chat_id, "❌ Minimum interval is 1 minute.")
            return "OK"

        interval = minutes * 60
        replied_msg = msg["reply_to_message"]

        if "media_group_id" in replied_msg:
            mgid = replied_msg["media_group_id"]
            key = (chat_id, mgid)
            _, message_ids = media_groups.get(key, (0, [replied_msg["message_id"]]))
            is_album = True
        else:
            message_ids = [replied_msg["message_id"]]
            is_album = False

        job_ref = {"running": True}
        repeat_jobs.setdefault(chat_id, []).append(job_ref)
        threading.Thread(
            target=repeater,
            args=(chat_id, message_ids, interval, job_ref, is_album),
            daemon=True
        ).start()

        send_message(chat_id, f"✅ Started repeating every <b>{minutes}</b> minute(s).", parse_mode="HTML")
        return "OK"

    # === /stop ===
    if text == "/stop":
        if not is_admin:
            send_message(chat_id, "❌ Only admins can use this command.")
            return "OK"

        if chat_id in repeat_jobs:
            for job in repeat_jobs[chat_id]:
                job["running"] = False
            repeat_jobs[chat_id] = []
            send_message(chat_id, "🛑 All repeating stopped.")
        else:
            send_message(chat_id, "ℹ️ No active repeat jobs.")
        return "OK"

    return "OK"

@app.route("/")
def index():
    return "Bot is running!"

# For platforms like Render, Replit, etc.
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))