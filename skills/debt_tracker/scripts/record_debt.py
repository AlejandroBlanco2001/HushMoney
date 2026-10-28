"""
Record money owed to or from the user.

Usage:
  python3 record_debt.py --person "João" --amount 35 --currency USD --direction they_owe
  python3 record_debt.py --person "Laura" --amount 12000 --currency COP --direction i_owe --description "lunch"

Output: {"ok": true, "id": "<uuid>"}
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import uuid
from datetime import UTC, datetime


DB_PATH = os.environ.get('HUSHMONEY_DB', os.path.expanduser('~/.hermes/hushmoney.db'))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--person', required=True)
    parser.add_argument('--amount', type=float, required=True)
    parser.add_argument('--currency', default='COP')
    parser.add_argument('--direction', required=True, choices=['i_owe', 'they_owe'])
    parser.add_argument('--description', default=None)
    args = parser.parse_args()

    now = datetime.now(UTC).isoformat()
    debt_id = str(uuid.uuid4())

    con = sqlite3.connect(DB_PATH)
    with con:
        con.execute(
            """INSERT INTO debts (id, person, amount, currency, direction, description, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                debt_id,
                args.person,
                args.amount,
                args.currency,
                args.direction,
                args.description,
                now,
            ),
        )
    con.close()

    print(json.dumps({'ok': True, 'id': debt_id}))


if __name__ == '__main__':
    main()
