"""
Return all unsettled debts, grouped by person.

Usage: python3 get_active_debts.py [--person "João"]
Output: {"debts": [...], "summary": {"João": {"net": 35.0, "currency": "USD", ...}}, "count": N}
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3


DB_PATH = os.environ.get('HUSHMONEY_DB', os.path.expanduser('~/.hermes/hushmoney.db'))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--person', default=None, help='Filter by person name (case-insensitive)')
    args = parser.parse_args()

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    where = 'settled_at IS NULL'
    params: list = []
    if args.person:
        where += ' AND LOWER(person) = LOWER(?)'
        params.append(args.person)

    rows = con.execute(
        f'SELECT * FROM debts WHERE {where} ORDER BY created_at DESC',
        params,
    ).fetchall()
    con.close()

    debts = [dict(r) for r in rows]

    summary: dict[str, dict] = {}
    for d in debts:
        person = d['person']
        currency = d['currency']
        if person not in summary:
            summary[person] = {'currency': currency, 'they_owe': 0.0, 'i_owe': 0.0}
        if d['direction'] == 'they_owe':
            summary[person]['they_owe'] += d['amount']
        else:
            summary[person]['i_owe'] += d['amount']

    for s in summary.values():
        s['net'] = round(s['they_owe'] - s['i_owe'], 2)

    print(json.dumps({'debts': debts, 'summary': summary, 'count': len(debts)}))


if __name__ == '__main__':
    main()
