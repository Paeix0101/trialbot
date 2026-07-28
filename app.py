from flask import Flask, render_template, request, redirect, session, jsonify
import json
import os
import random

app = Flask(__name__)
app.secret_key = "telegram_clone_demo"

USERS_FILE = "users.json"
MESSAGES_FILE = "messages.json"


# ---------------- USERS ---------------- #

def load_users():
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, "w") as f:
            json.dump([], f)

    with open(USERS_FILE, "r") as f:
        return json.load(f)


def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=4)


# ---------------- MESSAGES ---------------- #

def load_messages():
    if not os.path.exists(MESSAGES_FILE):
        with open(MESSAGES_FILE, "w") as f:
            json.dump([], f)

    with open(MESSAGES_FILE, "r") as f:
        return json.load(f)


def save_messages(messages):
    with open(MESSAGES_FILE, "w") as f:
        json.dump(messages, f, indent=4)


# ---------------- HOME ---------------- #

@app.route("/")
def home():

    a = random.randint(1, 9)
    b = random.randint(1, 9)

    session["captcha"] = a + b

    return render_template("index.html", a=a, b=b)


# ---------------- LOGIN ---------------- #

@app.route("/login", methods=["POST"])
def login():

    userid = request.form["userid"].strip().lower()
    captcha = int(request.form["captcha"])

    if captcha != session["captcha"]:
        return "Wrong Captcha"

    users = load_users()

    if userid not in users:
        users.append(userid)
        save_users(users)

    session["user"] = userid

    return redirect("/chat")


# ---------------- CHAT PAGE ---------------- #

@app.route("/chat")
def chat():

    if "user" not in session:
        return redirect("/")

    users = load_users()

    me = session["user"]

    users = [u for u in users if u != me]

    return render_template(
        "chat.html",
        users=users,
        me=me
    )


# ---------------- SEND MESSAGE ---------------- #

@app.route("/send", methods=["POST"])
def send():

    sender = session["user"]

    receiver = request.form["receiver"]

    message = request.form["message"]

    messages = load_messages()

    messages.append({

        "from": sender,
        "to": receiver,
        "message": message

    })

    save_messages(messages)

    return redirect("/chat")


# ---------------- LOAD CHAT ---------------- #

@app.route("/messages/<receiver>")
def messages(receiver):

    me = session["user"]

    all_messages = load_messages()

    chat = []

    for m in all_messages:

        if (
            (m["from"] == me and m["to"] == receiver)
            or
            (m["from"] == receiver and m["to"] == me)
        ):

            chat.append(m)

    return jsonify(chat)


# ---------------- LOGOUT ---------------- #

@app.route("/logout")
def logout():

    session.clear()

    return redirect("/")


# ---------------- RUN ---------------- #

if __name__ == "__main__":

    port = int(os.environ.get("PORT", 5000))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=True
    )