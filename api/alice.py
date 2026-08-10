from http.server import BaseHTTPRequestHandler
import os
import json
import re
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


def build_reply(req_body, text, end_session=False):
    return {
        "version": req_body.get("version", "1.0"),
        "session": req_body["session"],
        "response": {"text": text, "end_session": end_session},
    }


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        body = json.loads(raw)

        utterance = body.get("request", {}).get("original_utterance", "").strip()
        app_id = body.get("session", {}).get("application", {}).get("application_id")

        reply = None

        if not app_id:
            # На случай системных запросов от Яндекса без application_id
            reply = build_reply(body, "Не удалось определить устройство.")
        else:
            match = re.search(r"код\s*(\d{6})", utterance, re.IGNORECASE)
            if match:
                code = match.group(1)
                rows = supabase_request("GET", f"/bindings?code=eq.{code}&confirmed=eq.false")
                if not rows:
                    reply = build_reply(body, "Такой код не найден или уже использован.")
                else:
                    supabase_request(
                        "PATCH",
                        f"/bindings?code=eq.{code}",
                        {"alice_user_id": app_id, "confirmed": True},
                    )
                    reply = build_reply(body, "Готово, аккаунт привязан! Теперь можешь отправлять заметки.")

            if reply is None:
                match = re.search(r"заметк\w*\s+(?:о|про)?\s*(.+)", utterance, re.IGNORECASE)
                if match:
                    note_text = match.group(1).strip()
                    rows = supabase_request(
                        "GET", f"/bindings?alice_user_id=eq.{app_id}&confirmed=eq.true"
                    )
                    if not rows:
                        reply = build_reply(
                            body,
                            "Твой аккаунт ещё не привязан к Telegram. Напиши боту /start и назови мне полученный код.",
                        )
                    else:
                        chat_id = rows[0]["telegram_chat_id"]
                        send_telegram_message(chat_id, f"📝 Заметка от Алисы:\n{note_text}")
                        reply = build_reply(body, "Заметка отправлена в Telegram.")

            if reply is None:
                reply = build_reply(
                    body,
                    "Скажи, например: «отправь заметку о покупке персиков», или назови код привязки.",
                )

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(reply).encode())
