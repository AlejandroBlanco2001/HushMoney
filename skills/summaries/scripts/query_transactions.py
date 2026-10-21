"""
Query transactions for a period, joined with accounts and cards.

Usage:
  python3 query_transactions.py --period today
  python3 query_transactions.py --period week
  python3 query_transactions.py --period month
  python3 query_transactions.py --from 2026-10-01 --to 2026-10-31
  python3 query_transactions.py --period week --bank bancolombia
  python3 query_transactions.py --period month --category food

Output: {"transactions": [...], "total_by_currency": {"COP": 123456.0}, "count": N}
Each transaction includes account (bank, alias, type, masked_number) and card context.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import UTC, datetime, timedelta


DB_PATH = os.environ.get('HUSHMONEY_DB', os.path.expanduser('~/.hermes/hushmoney.db'))


def _period_bounds(period: str) -> tuple[str, str]:
    now = datetime.now(UTC)
    if period == 'today':
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == 'week':
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == 'month':
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        raise ValueError(f'Unknown period: {period}')
    return start.strftime('%Y-%m-%dT%H:%M:%SZ'), now.strftime('%Y-%m-%dT%H:%M:%SZ')


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--period', choices=['today', 'week', 'month'])
    group.add_argument('--from', dest='from_date', metavar='DATE')
    parser.add_argument('--to', dest='to_date', metavar='DATE')
    parser.add_argument('--bank', default=None)
    parser.add_argument('--category', default=None)
    parser.add_argument('--exclude-types', nargs='+',
                        default=['transfer_in'],
                        help='Transaction types to exclude (default: transfer_in)')
    args = parser.parse_args()

    if args.period:
        from_date, to_date = _period_bounds(args.period)
    elif args.from_date:
        from_date = args.from_date
        to_date = args.to_date or datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')
    else:
        from_date, to_date = _period_bounds('month')

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    where = ['t.date >= ?', 't.date <= ?']
    params: list = [from_date, to_date]

    if args.bank:
        where.append('a.bank = ?')
        params.append(args.bank)
    if args.category:
        where.append('t.category = ?')
        params.append(args.category)
    if args.exclude_types:
        placeholders = ','.join('?' for _ in args.exclude_types)
        where.append(f't.transaction_type NOT IN ({placeholders})')
        params.extend(args.exclude_types)

    sql = f"""
        SELECT
            t.id, t.amount, t.currency, t.merchant, t.date,
            t.transaction_type, t.channel, t.category, t.description,
            a.bank          AS acct_bank,
            a.alias         AS acct_alias,
            a.type          AS acct_type,
            a.masked_number AS acct_masked,
            c.alias         AS card_alias,
            c.masked_number AS card_masked,
            c.type          AS card_type
        FROM transactions t
        JOIN accounts a ON t.account_id = a.id
        LEFT JOIN cards c ON t.card_id = c.id
        WHERE {' AND '.join(where)}
        ORDER BY t.date DESC
    """

    rows = con.execute(sql, params).fetchall()
    con.close()

    transactions = []
    totals: dict[str, float] = {}
    for r in rows:
        tx: dict = {
            'id': r['id'],
            'amount': r['amount'],
            'currency': r['currency'],
            'merchant': r['merchant'],
            'date': r['date'],
            'transaction_type': r['transaction_type'],
            'channel': r['channel'],
            'category': r['category'],
            'description': r['description'],
            'account': {
                'bank': r['acct_bank'],
                'alias': r['acct_alias'],
                'type': r['acct_type'],
                'masked_number': r['acct_masked'],
            },
            'card': {
                'alias': r['card_alias'],
                'masked_number': r['card_masked'],
                'type': r['card_type'],
            } if r['card_masked'] else None,
        }
        transactions.append(tx)
        totals[r['currency']] = totals.get(r['currency'], 0.0) + r['amount']

    print(json.dumps({
        'transactions': transactions,
        'total_by_currency': totals,
        'count': len(transactions),
        'from': from_date,
        'to': to_date,
    }))


if __name__ == '__main__':
    main()
