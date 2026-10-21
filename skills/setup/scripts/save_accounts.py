"""
Create an account row during setup. Skips silently if a matching row already exists.
Matches on (bank, type, masked_number) when masked_number is provided,
otherwise on (bank, type, currency).

Usage:
  python3 save_accounts.py \
    --bank bancolombia \
    --type checking \
    --currency COP \
    [--masked-number "****1234"] \
    [--alias "Mi cuenta de ahorros"]

Output:
  {"ok": true, "id": "<uuid>", "created": true}   — new row inserted
  {"ok": true, "id": "<uuid>", "created": false}  — already existed, skipped
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import uuid
from datetime import UTC, datetime


DB_PATH = os.environ.get('HUSHMONEY_DB', os.path.expanduser('~/.hermes/hushmoney.db'))

VALID_TYPES     = {'checking', 'savings', 'credit', 'digital_wallet'}
VALID_BANKS     = {'bancolombia', 'davivienda', 'nequi', 'bbva', 'unknown'}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--bank',          required=True)
    parser.add_argument('--type',          required=True, dest='account_type',
                        choices=list(VALID_TYPES))
    parser.add_argument('--currency',      required=True)
    parser.add_argument('--masked-number', default=None,
                        help='Last-4 digits as they appear in notifications, e.g. ****1234')
    parser.add_argument('--alias',         default=None,
                        help='Friendly label shown in summaries')
    args = parser.parse_args()

    bank = args.bank.lower().strip()
    if bank not in VALID_BANKS:
        bank = 'unknown'

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        if args.masked_number:
            row = con.execute(
                'SELECT id FROM accounts WHERE bank = ? AND type = ? AND masked_number = ? LIMIT 1',
                (bank, args.account_type, args.masked_number),
            ).fetchone()
        else:
            row = con.execute(
                'SELECT id FROM accounts WHERE bank = ? AND type = ? AND currency = ? LIMIT 1',
                (bank, args.account_type, args.currency),
            ).fetchone()

        if row:
            print(json.dumps({'ok': True, 'id': str(row['id']), 'created': False}))
            return

        account_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        with con:
            con.execute(
                'INSERT INTO accounts (id, bank, alias, type, currency, masked_number, created_at)'
                ' VALUES (?, ?, ?, ?, ?, ?, ?)',
                (account_id, bank, args.alias, args.account_type,
                 args.currency, args.masked_number, now),
            )
    finally:
        con.close()

    print(json.dumps({'ok': True, 'id': account_id, 'created': True}))


if __name__ == '__main__':
    main()
