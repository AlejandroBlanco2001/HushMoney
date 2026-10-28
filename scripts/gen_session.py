#!/usr/bin/env python3
"""Generate a TELEGRAM_SESSION_STRING and save it to .env (or print it).

Usage:
    python gen_session.py              # prints to stdout
    python gen_session.py /path/.env   # writes/updates TELEGRAM_SESSION_STRING in .env
"""

import asyncio
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from pyrogram import Client


ENV_FILE = Path(sys.argv[1]) if len(sys.argv) > 1 else None

load_dotenv(ENV_FILE or Path(__file__).parent.parent / '.env')

API_ID = int(os.environ['TELEGRAM_API_ID'])
API_HASH = os.environ['TELEGRAM_API_HASH']


async def main() -> None:
    async with Client('gen', api_id=API_ID, api_hash=API_HASH) as app:
        session = await app.export_session_string()

    if ENV_FILE:
        content = ENV_FILE.read_text()
        line = f'TELEGRAM_SESSION_STRING={session}'
        if 'TELEGRAM_SESSION_STRING' in content:
            content = re.sub(r'TELEGRAM_SESSION_STRING=.*', line, content)
        else:
            content = content.rstrip('\n') + f'\n{line}\n'
        ENV_FILE.write_text(content)
        print(f'\nSession string saved to {ENV_FILE}')
    else:
        print(f'\nAdd this to your .env:\n\nTELEGRAM_SESSION_STRING={session}\n')


asyncio.run(main())
