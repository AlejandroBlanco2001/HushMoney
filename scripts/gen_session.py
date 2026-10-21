#!/usr/bin/env python3
"""Generate a TELEGRAM_SESSION_STRING and print it ready to paste into .env."""
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from pyrogram import Client

load_dotenv(Path(__file__).parent.parent / ".env")

API_ID   = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]


async def main() -> None:
    async with Client("gen", api_id=API_ID, api_hash=API_HASH) as app:
        session = await app.export_session_string()
    print("\nAdd this to your .env:\n")
    print(f"TELEGRAM_SESSION_STRING={session}\n")


asyncio.run(main())
