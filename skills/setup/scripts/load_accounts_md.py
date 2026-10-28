"""
Pre-load accounts from config/accounts.md if the user has filled it in.

Returns JSON:
  {"ready": false}                         — file missing or still has DELETE THIS line
  {"ready": true, "loaded": N, "skipped": N, "accounts": [...]}  — parsed and loaded
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path


DB_PATH = os.environ.get('HUSHMONEY_DB', os.path.expanduser('~/.hermes/hushmoney.db'))
SCHEMA_PATH = os.environ.get('HUSHMONEY_SCHEMA', '/app/config/schema.sql')
ACCOUNTS_MD = os.environ.get('HUSHMONEY_ACCOUNTS_MD', '/app/accounts.md')

VALID_TYPES = {'checking', 'savings', 'credit', 'digital_wallet'}
VALID_BANKS = {'bancolombia', 'davivienda', 'nequi', 'bbva'}


def _ensure_schema(con: sqlite3.Connection) -> None:
    if os.path.isfile(SCHEMA_PATH):
        con.executescript(open(SCHEMA_PATH).read())


def _parse_md(text: str) -> list[dict]:
    """Parse sections of the form `# bank / type` with key: value pairs below."""
    accounts = []
    current: dict | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()

        # Section header: # bancolombia / checking
        m = re.match(r'^#\s+([a-z0-9_]+)\s*/\s*([a-z_]+)\s*$', line, re.IGNORECASE)
        if m:
            if current:
                accounts.append(current)
            bank = m.group(1).lower().strip()
            acct_type = m.group(2).lower().strip()
            current = {
                'bank': bank if bank in VALID_BANKS else 'unknown',
                'type': acct_type if acct_type in VALID_TYPES else None,
                'alias': None,
                'currency': 'COP',
                'account_last4': None,
                'card_last4': None,
            }
            continue

        # Key: value pair inside a section
        if current and ':' in line and not line.startswith('#') and not line.startswith('-'):
            key, _, val = line.partition(':')
            key = key.strip().lower().replace(' ', '_').replace('-', '_')
            val = val.strip()
            if val.lower() == 'skip' or val == '':
                val = None
            if key == 'alias':
                current['alias'] = val
            elif key == 'currency':
                current['currency'] = (val or 'COP').upper()
            elif key == 'account_last4':
                current['account_last4'] = f'****{val}' if val else None
            elif key == 'card_last4':
                current['card_last4'] = f'****{val}' if val else None

    if current:
        accounts.append(current)

    return [a for a in accounts if a.get('type') in VALID_TYPES]


def _save_account(con: sqlite3.Connection, acc: dict) -> tuple[str, str | None, bool]:
    """Insert account (and optional card). Returns (account_id, card_id, created)."""
    masked = acc['account_last4']
    if masked:
        row = con.execute(
            'SELECT id FROM accounts WHERE bank=? AND type=? AND masked_number=? LIMIT 1',
            (acc['bank'], acc['type'], masked),
        ).fetchone()
    else:
        row = con.execute(
            'SELECT id FROM accounts WHERE bank=? AND type=? AND currency=? LIMIT 1',
            (acc['bank'], acc['type'], acc['currency']),
        ).fetchone()

    now = datetime.now(UTC).isoformat()
    created = False

    if row:
        account_id = str(row[0])
    else:
        account_id = str(uuid.uuid4())
        con.execute(
            'INSERT INTO accounts (id, bank, alias, type, currency, masked_number, created_at)'
            ' VALUES (?, ?, ?, ?, ?, ?, ?)',
            (account_id, acc['bank'], acc['alias'], acc['type'], acc['currency'], masked, now),
        )
        created = True

    card_id = None
    card_masked = acc['card_last4']
    if card_masked:
        card_row = con.execute(
            'SELECT id FROM cards WHERE account_id=? AND masked_number=? LIMIT 1',
            (account_id, card_masked),
        ).fetchone()
        if not card_row:
            card_id = str(uuid.uuid4())
            card_type = 'credit' if acc['type'] == 'credit' else 'debit'
            con.execute(
                'INSERT INTO cards (id, account_id, type, masked_number, alias, created_at)'
                ' VALUES (?, ?, ?, ?, ?, ?)',
                (card_id, account_id, card_type, card_masked, acc['alias'], now),
            )
        else:
            card_id = str(card_row[0])

    return account_id, card_id, created


def main() -> None:
    path = Path(ACCOUNTS_MD)
    if not path.is_file():
        print(json.dumps({'ready': False, 'reason': 'file_not_found'}))
        return

    text = path.read_text(encoding='utf-8')

    first_line = next((l for l in text.splitlines() if l.strip()), '')
    if 'DELETE THIS' in first_line:
        print(json.dumps({'ready': False, 'reason': 'template_not_filled'}))
        return

    accounts = _parse_md(text)
    if not accounts:
        print(json.dumps({'ready': False, 'reason': 'no_accounts_found'}))
        return

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    _ensure_schema(con)

    loaded, skipped, results = 0, 0, []
    with con:
        for acc in accounts:
            account_id, card_id, created = _save_account(con, acc)
            if created:
                loaded += 1
            else:
                skipped += 1
            results.append(
                {
                    'bank': acc['bank'],
                    'type': acc['type'],
                    'alias': acc['alias'],
                    'account_id': account_id,
                    'card_id': card_id,
                    'created': created,
                }
            )

    con.close()
    print(json.dumps({'ready': True, 'loaded': loaded, 'skipped': skipped, 'accounts': results}))


if __name__ == '__main__':
    main()
