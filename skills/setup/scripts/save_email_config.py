"""
Persists non-sensitive email configuration into user_settings.
The IMAP password is intentionally NOT stored here — it stays in .env only.

Usage:
  python3 save_email_config.py --provider gmail --host imap.gmail.com
                               --port 993 --username user@gmail.com
                               --bank-senders "a@bank.com,b@bank.com"
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import UTC, datetime


DB_PATH = os.environ.get('HUSHMONEY_DB', os.path.expanduser('~/.hermes/hushmoney.db'))


def upsert(con: sqlite3.Connection, key: str, value: str, now: str) -> None:
    con.execute(
        'INSERT INTO user_settings (key, value, updated_at) VALUES (?, ?, ?)'
        ' ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at',
        (key, value, now),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--provider', required=True, choices=['gmail', 'yahoo', 'outlook_forward', 'other']
    )
    parser.add_argument('--host', required=True)
    parser.add_argument('--port', type=int, default=993)
    parser.add_argument('--username', required=True)
    parser.add_argument('--bank-senders', required=True)
    args = parser.parse_args()

    now = datetime.now(UTC).isoformat()
    con = sqlite3.connect(DB_PATH)
    with con:
        upsert(con, 'email_provider', args.provider, now)
        upsert(con, 'imap_host', args.host, now)
        upsert(con, 'imap_port', str(args.port), now)
        upsert(con, 'imap_username', args.username, now)
        upsert(con, 'bank_sender_emails', args.bank_senders, now)
        upsert(con, 'setup_step', 'sms', now)
    con.close()

    print(json.dumps({'ok': True, 'provider': args.provider, 'username': args.username}))


if __name__ == '__main__':
    main()
