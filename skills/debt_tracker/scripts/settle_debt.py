"""
Mark a debt as settled.

Usage:
  python3 settle_debt.py --id <debt_uuid>
  python3 settle_debt.py --id <debt_uuid> --transaction-id <tx_uuid>
  python3 settle_debt.py --person "João" --all   # settle all debts with a person

Output: {"ok": true, "settled": N}
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import UTC, datetime


DB_PATH = os.environ.get('HUSHMONEY_DB', os.path.expanduser('~/.hermes/hushmoney.db'))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--id', default=None, help='Specific debt UUID to settle')
    parser.add_argument('--transaction-id', default=None, help='Linked transaction UUID')
    parser.add_argument('--person', default=None, help='Settle all debts with this person')
    parser.add_argument('--all', action='store_true', help='Use with --person to settle all')
    args = parser.parse_args()

    now = datetime.now(UTC).isoformat()
    con = sqlite3.connect(DB_PATH)

    if args.id:
        with con:
            cur = con.execute(
                """UPDATE debts SET settled_at = ?, settled_by_transaction_id = ?
                   WHERE id = ? AND settled_at IS NULL""",
                (now, args.transaction_id, args.id),
            )
        settled = cur.rowcount
    elif args.person and args.all:
        with con:
            cur = con.execute(
                """UPDATE debts SET settled_at = ?
                   WHERE LOWER(person) = LOWER(?) AND settled_at IS NULL""",
                (now, args.person),
            )
        settled = cur.rowcount
    else:
        con.close()
        print(json.dumps({'ok': False, 'error': 'provide --id or --person --all'}))
        return

    con.close()
    print(json.dumps({'ok': True, 'settled': settled}))


if __name__ == '__main__':
    main()
