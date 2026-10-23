"""
Mark a transaction as recurring.

Usage: python3 mark_recurring.py --id <tx_uuid>
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
    parser.add_argument("--id", required=True, help="Transaction UUID")
    args = parser.parse_args()

    now = datetime.now(UTC).isoformat()
    con = sqlite3.connect(DB_PATH)
    with con:
        con.execute(
            "UPDATE transactions SET is_recurring = 1, updated_at = ? WHERE id = ?",
            (now, args.id),
        )
    con.close()
    print(json.dumps({"ok": True}))


if __name__ == "__main__":
    main()
