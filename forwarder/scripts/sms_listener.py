#!/usr/bin/env python3
"""Watch Saved Messages, route each SMS through the forwarder sanitizer webhook.

Also exposes POST /inject on INJECT_PORT (default 9001): accepts {"text": "..."}
and sends the text from the user account to the Hermes bot so Hermes picks it up
via polling and can run skills (e.g. bank_learning) interactively.
"""
import asyncio
import json
import os
import queue as _queue
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import httpx
from dotenv import load_dotenv
from pyrogram import Client
from pyrogram.types import Message

load_dotenv()

API_ID   = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
MY_ID    = int(os.environ["TELEGRAM_CHAT_ID"])

_bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
BOT_ID = int(_bot_token.split(':')[0]) if ':' in _bot_token else 0

FORWARDER_URL  = os.environ.get("FORWARDER_WEBHOOK_URL", "http://forwarder:9000/telegram")
WEBHOOK_SECRET = os.environ["TELEGRAM_WEBHOOK_SECRET"]
INJECT_PORT    = int(os.environ.get("INJECT_PORT", "9001"))

app = Client(
    "sms_listener",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=os.environ.get("TELEGRAM_SESSION_STRING"),
)

_bot_target: int | str = 0  # set synchronously before app.run()
_app_loop: asyncio.AbstractEventLoop | None = None  # set before app.run()
_inject_queue: _queue.SimpleQueue[str] = _queue.SimpleQueue()


def _resolve_bot_sync() -> None:
    global _bot_target
    if not _bot_token:
        print("No TELEGRAM_BOT_TOKEN — inject disabled", flush=True)
        return
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(f"https://api.telegram.org/bot{_bot_token}/getMe")
            username = resp.json().get("result", {}).get("username", "")
        if username:
            _bot_target = f"@{username}"
            print(f"Inject target resolved: {_bot_target}", flush=True)
        else:
            _bot_target = BOT_ID
            print(f"Inject target fallback: {BOT_ID}", flush=True)
    except Exception as exc:
        _bot_target = BOT_ID
        print(f"Bot resolve failed, using ID {BOT_ID}: {exc}", flush=True)



class _InjectHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != '/inject':
            self.send_response(404)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        length = int(self.headers.get('Content-Length', 0))
        try:
            body = json.loads(self.rfile.read(length))
            text = body.get('text', '')
        except Exception:
            text = ''
        if text and _bot_target:
            _inject_queue.put(text)
        self.send_response(200)
        self.send_header('Content-Length', '2')
        self.end_headers()
        self.wfile.write(b'ok')

    def log_message(self, *args):
        pass


async def handle(client: Client, msg: Message) -> None:
    if msg.chat.id != MY_ID or not msg.text:
        return
    print(f"SMS received: {msg.text!r}", flush=True)
    update = {
        "update_id": msg.id,
        "message": {
            "message_id": msg.id,
            "date": int(msg.date.timestamp()) if msg.date else int(time.time()),
            "chat": {"id": MY_ID, "type": "private"},
            "from": {"id": MY_ID, "is_bot": False, "first_name": "User"},
            "text": msg.text,
        },
    }
    async with httpx.AsyncClient(timeout=15) as http:
        resp = await http.post(
            FORWARDER_URL,
            json=update,
            headers={"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET},
        )
    status = "ok" if resp.status_code == 200 else f"error {resp.status_code}"
    print(f"Forwarded: {status}", flush=True)


@app.on_message()
async def on_message(client: Client, msg: Message) -> None:
    await handle(client, msg)


async def _send_to_bot(text: str) -> None:
    await app.send_message(_bot_target, text)


def _sender_thread() -> None:
    while True:
        text = _inject_queue.get()
        loop = _app_loop
        if loop is None or not loop.is_running():
            # wait up to 30s for the loop to start
            for _ in range(300):
                time.sleep(0.1)
                if _app_loop is not None and _app_loop.is_running():
                    loop = _app_loop
                    break
        if loop is None or not loop.is_running():
            print(f"Inject dropped (loop not running): {text[:60]!r}", flush=True)
            continue
        try:
            future = asyncio.run_coroutine_threadsafe(_send_to_bot(text), loop)
            future.result(timeout=30)
            print(f"Injected to {_bot_target}: {text[:60]!r}...", flush=True)
        except Exception as exc:
            print(f"Inject send failed: {exc}", flush=True)


# --- startup: sync setup before app.run() ---
_resolve_bot_sync()

# Capture the loop that app.run() will use — same as the main thread's default loop.
_app_loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()

server = HTTPServer(('0.0.0.0', INJECT_PORT), _InjectHandler)
Thread(target=server.serve_forever, daemon=True).start()
Thread(target=_sender_thread, daemon=True).start()
print(f"Inject server listening on 0.0.0.0:{INJECT_PORT}", flush=True)

app.run()
