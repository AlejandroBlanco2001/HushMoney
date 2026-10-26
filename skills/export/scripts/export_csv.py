"""
Export transactions for a period to a CSV file the user can open in Excel/Sheets.

Usage:
  python3 export_csv.py                          # current month
  python3 export_csv.py --period week
  python3 export_csv.py --period month
  python3 export_csv.py --month 2026-09
  python3 export_csv.py --from 2026-09-01 --to 2026-09-30

Output: {"path": "/tmp/hushmoney_exports/hushmoney_2026-10.csv", "count": N,
         "period": "2026-10", "from": "...", "to": "..."}
"path" is null when the period has no transactions (no file is written).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path


DB_PATH = os.environ.get('HUSHMONEY_DB', os.path.expanduser('~/.hermes/hushmoney.db'))
DEFAULT_OUT_DIR = '/tmp/hushmoney_exports'
FILE_PREFIX = 'hushmoney_'
COLUMNS = ['date', 'merchant', 'amount', 'currency', 'category',
           'transaction_type', 'account', 'channel']
INCOME_TYPES = {'transfer_in', 'credit'}
# Spreadsheet apps evaluate cells starting with these as formulas; some locales
# also accept the full-width forms.
FORMULA_PREFIXES = ('=', '+', '-', '@', '\t', '\r', '\n', '＝', '＋', '－', '＠')
ISO = '%Y-%m-%dT%H:%M:%SZ'


def _start_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def _next_month(dt: datetime) -> datetime:
    return dt.replace(year=dt.year + 1, month=1) if dt.month == 12 else dt.replace(month=dt.month + 1)


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, '%Y-%m-%d').replace(tzinfo=UTC)


def resolve_period(args: argparse.Namespace, now: datetime) -> tuple[datetime, datetime, str]:
    """Return a half-open [start, end) range and a label for the file name."""
    if args.month:
        start = datetime.strptime(args.month, '%Y-%m').replace(tzinfo=UTC)
        return start, _next_month(start), args.month
    if args.from_date:
        start = _parse_date(args.from_date)
        end = _parse_date(args.to_date) + timedelta(days=1) if args.to_date else now
        last_day = (end - timedelta(seconds=1)).strftime('%Y-%m-%d')
        return start, end, f'{args.from_date}_{last_day}'
    if args.period == 'week':
        start = _start_of_day(now - timedelta(days=now.weekday()))
        year, week, _ = start.isocalendar()
        return start, now, f'{year}-W{week:02d}'
    start = _start_of_day(now.replace(day=1))
    return start, now, start.strftime('%Y-%m')


def fetch_transactions(con: sqlite3.Connection, start: datetime, end: datetime) -> list[sqlite3.Row]:
    con.row_factory = sqlite3.Row
    return con.execute(
        """
        SELECT t.date, t.merchant, t.amount, t.currency, t.category,
               t.transaction_type, t.channel,
               a.bank AS acct_bank, a.masked_number AS acct_masked
        FROM transactions t
        JOIN accounts a ON t.account_id = a.id
        WHERE t.date >= ? AND t.date < ?
        ORDER BY t.date
        """,
        (start.strftime(ISO), end.strftime(ISO)),
    ).fetchall()


def _safe_text(value: str | None) -> str:
    if not value:
        return ''
    return f"'{value}" if value.startswith(FORMULA_PREFIXES) else value


def _signed_amount(amount: float, transaction_type: str) -> str:
    signed = abs(amount) if transaction_type in INCOME_TYPES else -abs(amount)
    return str(int(signed)) if signed == int(signed) else f'{signed:.2f}'


def to_csv_row(row: sqlite3.Row) -> list[str]:
    account = ' '.join(p for p in (row['acct_bank'].title(), row['acct_masked']) if p)
    # The amount is built from a number here, never from message text, and must
    # stay unprefixed so a negative amount is still a number the sheet can sum.
    return [
        _safe_text(row['date']),
        _safe_text(row['merchant']),
        _signed_amount(row['amount'], row['transaction_type']),
        _safe_text(row['currency']),
        _safe_text(row['category']),
        _safe_text(row['transaction_type']),
        _safe_text(account),
        _safe_text(row['channel']),
    ]


def remove_previous_exports(out_dir: Path) -> None:
    # Hermes uploads the file after the turn ends, so a run cannot delete its own
    # output; instead each run clears whatever the previous export left behind.
    for old in out_dir.glob(f'{FILE_PREFIX}*.csv'):
        old.unlink()


def write_csv(path: Path, rows: list[sqlite3.Row]) -> None:
    # utf-8-sig adds a BOM so Excel shows accents (Nómina, Café) correctly.
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        # Quote every cell: Excel with a ';' list separator (es-CO) splits unquoted
        # cells, so "RAPPI;=1+1" would start a new cell that is a formula.
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        writer.writerow(COLUMNS)
        writer.writerows(to_csv_row(r) for r in rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--period', choices=['week', 'month'])
    group.add_argument('--month', metavar='YYYY-MM')
    group.add_argument('--from', dest='from_date', metavar='YYYY-MM-DD')
    parser.add_argument('--to', dest='to_date', metavar='YYYY-MM-DD')
    parser.add_argument('--out-dir', default=DEFAULT_OUT_DIR)
    args = parser.parse_args()
    if args.to_date and not args.from_date:
        parser.error('--to requires --from')

    start, end, label = resolve_period(args, datetime.now(UTC))
    con = sqlite3.connect(DB_PATH)
    rows = fetch_transactions(con, start, end)
    con.close()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    remove_previous_exports(out_dir)

    path = None
    if rows:
        path = out_dir / f'{FILE_PREFIX}{label}.csv'
        write_csv(path, rows)

    print(json.dumps({
        'path': str(path) if path else None,
        'count': len(rows),
        'period': label,
        'from': start.strftime(ISO),
        'to': end.strftime(ISO),
    }))


if __name__ == '__main__':
    main()
