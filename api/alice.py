from http.server import BaseHTTPRequestHandler
import os
import json
import re
import urllib.request
import urllib.error

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

CODE_RE = re.compile(r"(?:код\s*)?\b(\d{6})\b", re.IGNORECASE)
NOTE_TRIGGER_RE = re.compile(
    r"(?:заметк\w*|запиши|сохрани|напомни)\w*\s+(?:мне\s+)?(?:о\s+|про\s+|что\s+)?(.+)",
    re.IGNORECASE,
)


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
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode())


def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = json.dumps({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=8)


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
            note_match = NOTE_TRIGGER_RE.search(utterance)

            # Заметка проверяется первой, чтобы случайные 6 цифр внутри
            # текста заметки не перехватывались как код привязки.
            if note_match:
                note_text = note_match.group(1).strip()
                try:
                    rows = supabase_request(
                        "GET", f"/bindings?alice_user_id=eq.{app_id}&confirmed=eq.true"
                    )
                except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                    reply = build_reply(
                        body, "Не получилось связаться с сервисом привязки, попробуй чуть позже."
                    )
                else:
                    if not rows:
                        reply = build_reply(
                            body,
                            "Твой аккаунт ещё не привязан к Telegram. Напиши боту /start и назови мне полученный код.",
                        )
                    else:
                        chat_id = rows[0]["telegram_chat_id"]
                        try:
                            send_telegram_message(chat_id, f"📝 Заметка от Алисы:\n{note_text}")
                        except (urllib.error.URLError, TimeoutError):
                            reply = build_reply(
                                body, "Не получилось отправить заметку в Telegram, попробуй ещё раз."
                            )
                        else:
                            reply = build_reply(body, "Заметка отправлена в Telegram.")

            if reply is None:
                code_match = CODE_RE.search(utterance)
                if code_match:
                    code = code_match.group(1)
                    try:
                        rows = supabase_request("GET", f"/bindings?code=eq.{code}")
                    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                        reply = build_reply(
                            body, "Не получилось связаться с сервисом привязки, попробуй чуть позже."
                        )
                    else:
                        if not rows:
                            reply = build_reply(body, "Такой код не найден. Проверь его в Telegram-боте.")
                        elif rows[0]["confirmed"]:
                            reply = build_reply(body, "Этот код уже был использован ранее.")
                        else:
                            try:
                                supabase_request(
                                    "PATCH",
                                    f"/bindings?code=eq.{code}",
                                    {"alice_user_id": app_id, "confirmed": True},
                                )
                            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                                reply = build_reply(
                                    body, "Не получилось сохранить привязку, попробуй чуть позже."
                                )
                            else:
                                reply = build_reply(
                                    body, "Готово, аккаунт привязан! Теперь можешь отправлять заметки."
                                )

            if reply is None:
                reply = build_reply(
                    body,
                    "Скажи, например: «заметка купить молоко», «запиши позвонить маме», "
                    "или назови код привязки.",
                )

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(reply).encode())
