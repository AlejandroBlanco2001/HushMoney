"""
Marks setup as complete and records the timestamp.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime


DB_PATH = os.environ.get('HUSHMONEY_DB', os.path.expanduser('~/.hermes/hushmoney.db'))


def main() -> None:
    now = datetime.now(UTC).isoformat()
    con = sqlite3.connect(DB_PATH)
    with con:
        for key, value in [
            ('setup_complete', 'true'),
            ('setup_step', 'done'),
            ('setup_completed_at', now),
        ]:
            con.execute(
                'INSERT INTO user_settings (key, value, updated_at) VALUES (?, ?, ?)'
                ' ON CONFLICT(key) DO UPDATE SET'
                ' value = excluded.value, updated_at = excluded.updated_at',
                (key, value, now),
            )
    con.close()
    print(json.dumps({'ok': True, 'completed_at': now}))


if __name__ == '__main__':
    main()
