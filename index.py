import os
import json
import random
import string
import re
import urllib.request
from flask import Flask, request, jsonify

app = Flask(__name__)

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]


def supabase_request(method, path, body=None):
    url = f"{SUPABASE_URL}/rest/v1{path}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = json.dumps({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req)


def generate_code():
    return "".join(random.choices(string.digits, k=6))


@app.route("/api/telegram", methods=["POST"])
def telegram_webhook():
    body = request.get_json(force=True)
    message = body.get("message")
    if not message:
        return jsonify({"ok": True})

    chat_id = message["chat"]["id"]
    text = message.get("text", "")

    if text == "/start":
        code = generate_code()
        supabase_request("POST", "/bindings", {
            "code": code,
            "telegram_chat_id": chat_id,
            "confirmed": False,
        })
        send_telegram_message(
            chat_id,
            "Привет! Чтобы получать заметки от Алисы, скажи ей:\n\n"
            f"«Алиса, запусти [название навыка], привяжи код {code}»\n\n"
            "Код одноразовый."
        )
    else:
        send_telegram_message(chat_id, "Напиши /start, чтобы получить код привязки к Алисе.")

    return jsonify({"ok": True})


@app.route("/api/alice", methods=["POST"])
def alice_webhook():
    body = request.get_json(force=True)
    utterance = body["request"]["original_utterance"].strip()
    user_id = body["session"]["user"]["user_id"]

    def alice_reply(text, end_session=False):
        return jsonify({
            "version": body.get("version", "1.0"),
            "session": body["session"],
            "response": {"text": text, "end_session": end_session},
        })

    match = re.search(r"код\s*(\d{6})", utterance, re.IGNORECASE)
    if match:
        code = match.group(1)
        rows = supabase_request("GET", f"/bindings?code=eq.{code}&confirmed=eq.false")
        if not rows:
            return alice_reply("Такой код не найден или уже использован.")
        supabase_request(
            "PATCH",
            f"/bindings?code=eq.{code}",
            {"alice_user_id": user_id, "confirmed": True},
        )
        return alice_reply("Готово, аккаунт привязан! Теперь можешь отправлять заметки.")

    match = re.search(r"заметк\w*\s+(?:о|про)?\s*(.+)", utterance, re.IGNORECASE)
    if match:
        note_text = match.group(1).strip()
        rows = supabase_request(
            "GET", f"/bindings?alice_user_id=eq.{user_id}&confirmed=eq.true"
        )
        if not rows:
            return alice_reply(
                "Твой аккаунт ещё не привязан к Telegram. Напиши боту /start и назови мне полученный код."
            )
        chat_id = rows[0]["telegram_chat_id"]
        send_telegram_message(chat_id, f"📝 Заметка от Алисы:\n{note_text}")
        return alice_reply("Заметка отправлена в Telegram.")

    return alice_reply(
        "Скажи, например: «отправь заметку о покупке персиков», или назови код привязки."
    )
