"""
Insert a confirmed learned pattern.

Usage:
  python3 store_pattern.py \
    --bank davivienda --country CO --channel sms \
    --pattern '{"transaction_type": "debit", "regex": "..."}' \
    [--confirmed]

Output: {"ok": true, "id": N}
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
    parser.add_argument('--bank',      required=True)
    parser.add_argument('--country',   default='CO')
    parser.add_argument('--channel',   required=True, choices=['sms', 'email'])
    parser.add_argument('--pattern',   required=True, help='JSON extraction rules')
    parser.add_argument('--confirmed', action='store_true')
    args = parser.parse_args()

    try:
        json.loads(args.pattern)
    except json.JSONDecodeError as e:
        print(json.dumps({'ok': False, 'error': f'Invalid pattern JSON: {e}'}))
        return

    now = datetime.now(UTC).isoformat()
    con = sqlite3.connect(DB_PATH)
    with con:
        cur = con.execute(
            '''INSERT INTO learned_patterns
               (bank_slug, country, channel, pattern, confirmed, uses, active, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 0, 1, ?, ?)''',
            (args.bank, args.country, args.channel, args.pattern,
             1 if args.confirmed else 0, now, now),
        )
    con.close()
    print(json.dumps({'ok': True, 'id': cur.lastrowid}))


if __name__ == '__main__':
    main()
