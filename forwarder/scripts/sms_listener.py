#!/usr/bin/env python3
"""Watch Saved Messages, route each SMS through the forwarder sanitizer webhook."""
import os
import time

import httpx
from dotenv import load_dotenv
from pyrogram import Client
from pyrogram.types import Message

load_dotenv()

API_ID   = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
MY_ID    = int(os.environ["TELEGRAM_CHAT_ID"])

FORWARDER_URL  = os.environ.get("FORWARDER_WEBHOOK_URL", "http://forwarder:9000/telegram")
WEBHOOK_SECRET = os.environ["TELEGRAM_WEBHOOK_SECRET"]

app = Client(
    "sms_listener",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=os.environ.get("TELEGRAM_SESSION_STRING"),
)


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


app.run()
