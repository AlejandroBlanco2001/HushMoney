"""
Insert a CleanPayload into the transactions table.
Finds or creates an account matching (bank, account_type, currency).
Silently skips duplicate message_hashes (idempotent).

Usage:
  python3 store_transaction.py \
    --amount 6930 --currency COP \
    --date 2026-10-21T09:56:00Z \
    --transaction-type debit \
    --account-type checking \
    --channel sms \
    [--merchant UBER] \
    [--bank bancolombia] \
    [--message-hash <sha256_hex>]

Output: {"ok": true, "id": "<uuid>", "duplicate": false}
        {"ok": true, "duplicate": true}   (hash already present — no insert)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import uuid
from datetime import UTC, datetime


DB_PATH = os.environ.get('HUSHMONEY_DB', os.path.expanduser('~/.hermes/hushmoney.db'))


def _find_or_create_account(
    con: sqlite3.Connection,
    bank: str,
    account_type: str,
    currency: str,
    now: str,
) -> str:
    row = con.execute(
        'SELECT id FROM accounts WHERE bank = ? AND type = ? AND currency = ? LIMIT 1',
        (bank, account_type, currency),
    ).fetchone()
    if row:
        return str(row[0])
    account_id = str(uuid.uuid4())
    con.execute(
        'INSERT INTO accounts (id, bank, type, currency, created_at) VALUES (?, ?, ?, ?, ?)',
        (account_id, bank, account_type, currency, now),
    )
    return account_id


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--amount', type=float, required=True)
    parser.add_argument('--currency', required=True)
    parser.add_argument('--date', required=True, help='ISO 8601 UTC')
    parser.add_argument(
        '--transaction-type',
        required=True,
        choices=['debit', 'credit', 'cash', 'transfer_in', 'transfer_out', 'payment', 'top_up'],
    )
    parser.add_argument(
        '--account-type', required=True, choices=['checking', 'savings', 'credit', 'digital_wallet']
    )
    parser.add_argument('--channel', required=True, choices=['email', 'sms'])
    parser.add_argument('--merchant', default=None)
    parser.add_argument('--bank', default='unknown')
    parser.add_argument(
        '--message-hash',
        default=None,
        help='SHA-256 hex fingerprint for dedup; computed if omitted',
    )
    parser.add_argument('--template-id', default=None)
    parser.add_argument('--pattern-status', default='active', choices=['active', 'candidate'])
    args = parser.parse_args()

    message_hash = (
        args.message_hash
        or hashlib.sha256(
            f'{args.amount}:{args.date}:{args.transaction_type}:{args.account_type}'.encode()
        ).hexdigest()
    )

    con = sqlite3.connect(DB_PATH)
    try:
        row = con.execute(
            'SELECT 1 FROM transactions WHERE message_hash = ? LIMIT 1', (message_hash,)
        ).fetchone()
        if row:
            print(json.dumps({'ok': True, 'duplicate': True}))
            return

        now = datetime.now(UTC).isoformat()
        with con:
            account_id = _find_or_create_account(
                con, args.bank, args.account_type, args.currency, now
            )
            transaction_id = str(uuid.uuid4())
            con.execute(
                """INSERT INTO transactions
                   (id, account_id, amount, currency, merchant, date,
                    transaction_type, channel, message_hash,
                    template_id, pattern_status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    transaction_id,
                    account_id,
                    args.amount,
                    args.currency,
                    args.merchant,
                    args.date,
                    args.transaction_type,
                    args.channel,
                    message_hash,
                    args.template_id,
                    args.pattern_status,
                    now,
                    now,
                ),
            )
    finally:
        con.close()

    print(json.dumps({'ok': True, 'id': transaction_id, 'duplicate': False}))


if __name__ == '__main__':
    main()
