"""
Ensures user_settings rows exist and returns current setup state as JSON.
Safe to run multiple times — only inserts rows that don't already exist.

Output JSON:
  { "setup_complete": "true"|"false", "setup_step": "<step>" }
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime


DB_PATH = os.environ.get('HUSHMONEY_DB', os.path.expanduser('~/.hermes/hushmoney.db'))
_SCHEMA_PATH = os.environ.get('HUSHMONEY_SCHEMA', '/app/config/schema.sql')

DEFAULTS: dict[str, str] = {
    'setup_complete': 'false',
    'setup_step': 'start',
    'email_provider': '',
    'imap_host': '',
    'imap_port': '993',
    'imap_username': '',
    'bank_sender_emails': '',
    'accounts_configured': 'false',
    'sms_channel_enabled': 'false',
}


def _ensure_schema(con: sqlite3.Connection) -> None:
    schema_path = os.path.abspath(_SCHEMA_PATH)
    if os.path.isfile(schema_path):
        with open(schema_path) as f:
            con.executescript(f.read())


def main() -> None:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    _ensure_schema(con)
    now = datetime.now(UTC).isoformat()

    with con:
        for key, value in DEFAULTS.items():
            con.execute(
                'INSERT OR IGNORE INTO user_settings (key, value, updated_at) VALUES (?, ?, ?)',
                (key, value, now),
            )

    rows = con.execute('SELECT key, value FROM user_settings').fetchall()
    settings = {row['key']: row['value'] for row in rows}
    con.close()

    print(
        json.dumps(
            {
                'setup_complete': settings.get('setup_complete', 'false'),
                'setup_step': settings.get('setup_step', 'start'),
            }
        )
    )


if __name__ == '__main__':
    main()
