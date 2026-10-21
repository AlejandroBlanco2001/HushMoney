#!/usr/bin/env python3
"""Watch Saved Messages, forward each message to the bot as a real user message, then delete it."""
import os
from pathlib import Path

from dotenv import load_dotenv
from pyrogram import Client
from pyrogram.types import Message

load_dotenv(Path(__file__).parent.parent / ".env")

API_ID       = int(os.environ["TELEGRAM_API_ID"])
API_HASH     = os.environ["TELEGRAM_API_HASH"]
BOT_USERNAME = os.environ["BOT_USERNAME"]
MY_ID        = int(os.environ["TELEGRAM_CHAT_ID"])

app = Client(
    "sms_listener",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=os.environ.get("TELEGRAM_SESSION_STRING"),
)


async def handle(client: Client, msg: Message) -> None:
    if msg.chat.id != MY_ID or not msg.text:
        return
    print(f"SMS received: {msg.text!r}")
    await client.send_message(BOT_USERNAME, msg.text)
    print("Done.")


@app.on_message()
async def on_message(client: Client, msg: Message) -> None:
    await handle(client, msg)


app.run()
