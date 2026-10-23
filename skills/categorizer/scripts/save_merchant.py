"""
Store or update a merchant entry in the merchants cache.

Usage:
  python3 save_merchant.py --name "MCD" --category food
  python3 save_merchant.py --name "RAPPI" --needs-clarification
  python3 save_merchant.py --name "RAPPI" --needs-clarification --last-category food
  python3 save_merchant.py --name "NETFLIX" --category entertainment --is-recurring

Output: {"ok": true}
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import UTC, datetime


DB_PATH = os.environ.get("HUSHMONEY_DB", os.path.expanduser("~/.hermes/hushmoney.db"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True, help="Merchant name (will be normalized)")
    parser.add_argument("--category", default=None)
    parser.add_argument("--needs-clarification", action="store_true")
    parser.add_argument("--last-category", default=None, help="Most recent confirmed category")
    parser.add_argument("--is-recurring", action="store_true")
    args = parser.parse_args()

    name = " ".join(args.name.split()).upper()
    now = datetime.now(UTC).isoformat()

    con = sqlite3.connect(DB_PATH)
    with con:
        con.execute(
            """
            INSERT INTO merchants (name, category, needs_clarification, last_category, is_recurring, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                category            = excluded.category,
                needs_clarification = excluded.needs_clarification,
                last_category       = COALESCE(excluded.last_category, last_category),
                is_recurring        = MAX(is_recurring, excluded.is_recurring),
                updated_at          = excluded.updated_at
            """,
            (name, args.category, int(args.needs_clarification), args.last_category,
             int(args.is_recurring), now, now),
        )
    con.close()
    print(json.dumps({"ok": True}))


if __name__ == "__main__":
    main()
