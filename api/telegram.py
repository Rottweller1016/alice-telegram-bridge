from http.server import BaseHTTPRequestHandler
import os
import json
import random
import string
import urllib.request

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


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        body = json.loads(raw)
        message = body.get("message")

        if message:
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

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')
