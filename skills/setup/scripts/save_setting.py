"""
Upserts a single user_settings row.
Usage: python3 save_setting.py <key> <value>
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import UTC, datetime


DB_PATH = os.environ.get('HUSHMONEY_DB', os.path.expanduser('~/.hermes/hushmoney.db'))


def main() -> None:
    if len(sys.argv) != 3:
        print(json.dumps({'error': 'usage: save_setting.py <key> <value>'}))
        sys.exit(1)

    key, value = sys.argv[1], sys.argv[2]
    now = datetime.now(UTC).isoformat()

    con = sqlite3.connect(DB_PATH)
    with con:
        con.execute(
            'INSERT INTO user_settings (key, value, updated_at) VALUES (?, ?, ?)'
            ' ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at',
            (key, value, now),
        )
    con.close()

    print(json.dumps({'ok': True, 'key': key}))


if __name__ == '__main__':
    main()
