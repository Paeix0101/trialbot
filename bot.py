import os
import time
import threading
from flask import Flask, request
import requests

TOKEN = os.environ.get("BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
BOT_API = f"https://api.telegram.org/bot{TOKEN}"

OWNER_ID = 8141547148
MONITOR_ID = 8405313334

app = Flask(__name__)

repeat_jobs = {}
groups_file = "groups.txt"

# FIXED: media_group storage with timestamps
media_groups = {}  # (chat_id, media_group_id): {"msgs": [], "last": timestamp}

last_broadcast_ids = {}

# ------------------------------------------------ #
def send_message(chat_id, text, parse_mode=None):
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    return requests.post(f"{BOT_API}/sendMessage", json=payload)


def delete_message(chat_id, message_id):
    return requests.post(
        f"{BOT_API}/deleteMessage",
        json={"chat_id": chat_id, "message_id": message_id},
    )


def get_chat_administrators(chat_id):
    r = requests.get(f"{BOT_API}/getChatAdministrators", params={"chat_id": chat_id})
    if r.ok and r.json().get("ok"):
        return r.json()["result"]
    return []


def export_invite_link(chat_id):
    r = requests.get(f"{BOT_API}/exportChatInviteLink", params={"chat_id": chat_id})
    if r.ok and r.json().get("ok"):
        return r.json()["result"]
    return None


def check_required_permissions(chat_id):
    admins = get_chat_administrators(chat_id)
    bot_id = requests.get(f"{BOT_API}/getMe").json()["result"]["id"]
    for a in admins:
        if a["user"]["id"] == bot_id:
            return all(
                [
                    a.get("can_delete_messages"),
                    a.get("can_restrict_members"),
                    a.get("can_invite_users"),
                    a.get("can_promote_members"),
                ]
            )
    return False


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
        return f.read().splitlines()


# ------------------------------------------------ #
# CLEANUP THREAD (NEW)
def cleanup_albums():
    while True:
        now = time.time()
        for key in list(media_groups.keys()):
            if now - media_groups[key]["last"] > 60:
                del media_groups[key]
        time.sleep(30)


threading.Thread(target=cleanup_albums, daemon=True).start()

# ------------------------------------------------ #
@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json()
    msg = update.get("message") or update.get("channel_post")
    my_chat_member = update.get("my_chat_member")

    if my_chat_member:
        chat = my_chat_member["chat"]
        chat_id = chat["id"]
        chat_title = chat.get("title", "")
        new_status = my_chat_member["new_chat_member"]["status"]

        if new_status in ["administrator", "member"]:
            if not check_required_permissions(chat_id):
                send_message(
                    OWNER_ID, f"❌ Missing required permissions in {chat_title} ({chat_id})"
                )
                return "OK"
            save_group_id(chat_id)
        return "OK"

    if not msg:
        return "OK"

    chat_id = msg["chat"]["id"]
    text = msg.get("text", "") or msg.get("caption", "")
    from_user = msg.get("from", {}).get("id")

    if str(chat_id).startswith("-"):
        save_group_id(chat_id)

    admins = (
        [a["user"]["id"] for a in get_chat_administrators(chat_id)]
        if str(chat_id).startswith("-")
        else []
    )
    is_admin = from_user in admins if from_user else True

    # FIXED: Collect album messages with timestamp
    if "media_group_id" in msg:
        key = (chat_id, msg["media_group_id"])
        media_groups.setdefault(key, {"msgs": [], "last": time.time()})
        media_groups[key]["msgs"].append(msg["message_id"])
        media_groups[key]["last"] = time.time()

    # ------------------------------------------------ #
    if text.strip().lower() == "/start":
        send_message(chat_id, "🤖 Repeat Messages Bot is running!", "HTML")
        return "OK"

    # ------------------------------------------------ #
    if "reply_to_message" in msg and text.startswith("/repeat"):
        if not is_admin:
            send_message(chat_id, "Only admins can use this command.")
            return "OK"

        replied = msg["reply_to_message"]
        command = text.split()[0].lower()

        interval_map = {
            "/repeat1min": (60, "1 minute"),
            "/repeat3min": (180, "3 minutes"),
            "/repeat5min": (300, "5 minutes"),
            "/repeat20min": (1200, "20 minutes"),
            "/repeat60min": (3600, "60 minutes"),
            "/repeat120min": (7200, "120 minutes"),
            "/repeat24hours": (86400, "24 hours"),
        }

        if command not in interval_map:
            send_message(chat_id, "Invalid repeat command.")
            return "OK"

        interval, label = interval_map[command]

        # FIXED: Album detection with delay
        if "media_group_id" in replied:
            key = (chat_id, replied["media_group_id"])
            time.sleep(1.2)  # IMPORTANT DELAY

            album_msgs = media_groups.get(key, {}).get(
                "msgs", [replied["message_id"]]
            )

            job = {
                "message_ids": album_msgs,
                "running": True,
                "interval": interval,
                "is_album": True,
            }

            repeat_jobs.setdefault(chat_id, []).append(job)
            threading.Thread(
                target=repeater,
                args=(chat_id, album_msgs, interval, job, True),
                daemon=True,
            ).start()

            send_message(chat_id, f"✅ Album repeating every {label}.")
        else:
            mid = replied["message_id"]
            job = {
                "message_ids": [mid],
                "running": True,
                "interval": interval,
                "is_album": False,
            }

            repeat_jobs.setdefault(chat_id, []).append(job)
            threading.Thread(
                target=repeater,
                args=(chat_id, [mid], interval, job, False),
                daemon=True,
            ).start()

            send_message(chat_id, f"✅ Message repeating every {label}.")

    elif text.startswith("/stop"):
        if not is_admin:
            send_message(chat_id, "Only admins can use this command.")
            return "OK"

        for job in repeat_jobs.get(chat_id, []):
            job["running"] = False
        repeat_jobs[chat_id] = []
        send_message(chat_id, "🛑 All repeating stopped.")

    return "OK"


@app.route("/")
def index():
    return "Bot is running!"


# ------------------------------------------------ #
def repeater(chat_id, message_ids, interval, job_ref, is_album):
    last_sent = []
    while job_ref["running"]:
        for m in last_sent:
            delete_message(chat_id, m)
        last_sent = []

        if is_album:
            r = requests.post(
                f"{BOT_API}/copyMessages",
                json={
                    "chat_id": chat_id,
                    "from_chat_id": chat_id,
                    "message_ids": message_ids,
                },
            )
            if r.ok and r.json().get("ok"):
                last_sent = [m["message_id"] for m in r.json()["result"]]
        else:
            r = requests.post(
                f"{BOT_API}/copyMessage",
                json={
                    "chat_id": chat_id,
                    "from_chat_id": chat_id,
                    "message_id": message_ids[0],
                },
            )
            if r.ok:
                last_sent = [r.json()["result"]["message_id"]]

        time.sleep(interval)


# ------------------------------------------------ #
def keep_alive():
    while True:
        try:
            requests.get(WEBHOOK_URL)
        except:
            pass
        time.sleep(300)


if __name__ == "__main__":
    requests.get(f"{BOT_API}/setWebhook?url={WEBHOOK_URL}/webhook")
    threading.Thread(target=keep_alive, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
