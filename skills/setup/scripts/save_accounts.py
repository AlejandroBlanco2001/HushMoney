"""
Create an account row (and optionally a linked card) during setup.
Idempotent: skips silently if a matching row already exists.

Usage:
  python3 save_accounts.py \
    --bank bancolombia \
    --type checking \
    --currency COP \
    [--masked-number "****1234"]       # last-4 of account number
    [--card-masked-number "****5678"]  # last-4 of linked card
    [--alias "Debito Bancolombia"]

Output:
  {"ok": true, "account_id": "<uuid>", "card_id": "<uuid>|null", "created": true|false}
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import uuid
from datetime import UTC, datetime


DB_PATH = os.environ.get('HUSHMONEY_DB', os.path.expanduser('~/.hermes/hushmoney.db'))
SCHEMA_PATH = os.environ.get('HUSHMONEY_SCHEMA', '/app/config/schema.sql')

VALID_TYPES = {'checking', 'savings', 'credit', 'digital_wallet'}
VALID_BANKS = {'bancolombia', 'davivienda', 'nequi', 'bbva', 'unknown'}


def _ensure_schema(con: sqlite3.Connection) -> None:
    if os.path.isfile(SCHEMA_PATH):
        con.executescript(open(SCHEMA_PATH).read())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--bank', required=True)
    parser.add_argument('--type', required=True, dest='account_type', choices=list(VALID_TYPES))
    parser.add_argument('--currency', required=True)
    parser.add_argument(
        '--masked-number', default=None, help='Last-4 digits of the account number (****1234)'
    )
    parser.add_argument(
        '--card-masked-number', default=None, help='Last-4 digits of the linked card (****5678)'
    )
    parser.add_argument('--alias', default=None)
    args = parser.parse_args()

    bank = args.bank.lower().strip()
    if bank not in VALID_BANKS:
        bank = 'unknown'

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    _ensure_schema(con)

    try:
        # Find or create the account
        if args.masked_number:
            row = con.execute(
                'SELECT id FROM accounts WHERE bank=? AND type=? AND masked_number=? LIMIT 1',
                (bank, args.account_type, args.masked_number),
            ).fetchone()
        else:
            row = con.execute(
                'SELECT id FROM accounts WHERE bank=? AND type=? AND currency=? LIMIT 1',
                (bank, args.account_type, args.currency),
            ).fetchone()

        created = False
        if row:
            account_id = str(row['id'])
        else:
            account_id = str(uuid.uuid4())
            now = datetime.now(UTC).isoformat()
            with con:
                con.execute(
                    'INSERT INTO accounts (id, bank, alias, type, currency, masked_number, created_at)'
                    ' VALUES (?, ?, ?, ?, ?, ?, ?)',
                    (
                        account_id,
                        bank,
                        args.alias,
                        args.account_type,
                        args.currency,
                        args.masked_number,
                        now,
                    ),
                )
            created = True

        # Create linked card if card number provided
        card_id = None
        if args.card_masked_number:
            card_row = con.execute(
                'SELECT id FROM cards WHERE account_id=? AND masked_number=? LIMIT 1',
                (account_id, args.card_masked_number),
            ).fetchone()
            if not card_row:
                card_id = str(uuid.uuid4())
                card_type = 'credit' if args.account_type == 'credit' else 'debit'
                now = datetime.now(UTC).isoformat()
                with con:
                    con.execute(
                        'INSERT INTO cards (id, account_id, type, masked_number, alias, created_at)'
                        ' VALUES (?, ?, ?, ?, ?, ?)',
                        (card_id, account_id, card_type, args.card_masked_number, args.alias, now),
                    )
            else:
                card_id = str(card_row['id'])

    finally:
        con.close()

    print(
        json.dumps({'ok': True, 'account_id': account_id, 'card_id': card_id, 'created': created})
    )


if __name__ == '__main__':
    main()
