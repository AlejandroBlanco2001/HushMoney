"""
Query spending for a period, joined with accounts and cards, and compare it with the
previous period.

Usage:
  python3 query_transactions.py --period today
  python3 query_transactions.py --period week                # this week so far
  python3 query_transactions.py --period week --offset -1    # last Monday–Sunday week
  python3 query_transactions.py --period month --offset -1   # last calendar month
  python3 query_transactions.py --from 2026-10-01 --to 2026-10-31
  python3 query_transactions.py --period week --bank bancolombia
  python3 query_transactions.py --period month --category food

Periods are the user's local days (user_settings.timezone, default America/Bogota).
Week and month periods are compared against the previous period of the same length
so far, and come with the Telegram message rendered in "text". Other periods have
no comparison and "text": null.

Output: {"transactions": [...], "total_by_currency": {"COP": 123456.0}, "count": N,
         "from": ..., "to": ... (exclusive), "period": "week", "timezone": ...,
         "spending_by_category": [...], "income_by_currency": {...},
         "previous": {...} | null, "biggest_change": {...}, "text": "..." | null}
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from string import Template
from typing import TypedDict
from zoneinfo import ZoneInfo


DB_PATH = os.environ.get('HUSHMONEY_DB', os.path.expanduser('~/.hermes/hushmoney.db'))
SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_TIMEZONE = 'America/Bogota'
ISO = '%Y-%m-%dT%H:%M:%SZ'
INCOME_TYPES = ('transfer_in', 'credit')
TEMPLATE_BY_PERIOD = {'week': 'weekly', 'month': 'monthly'}
COMPARISON_BY_PERIOD = {'week': 'vs sem. anterior', 'month': 'vs mes anterior'}
MONTHS = (
    'enero',
    'febrero',
    'marzo',
    'abril',
    'mayo',
    'junio',
    'julio',
    'agosto',
    'septiembre',
    'octubre',
    'noviembre',
    'diciembre',
)
DEFAULT_EMOJI = '🏷️'
# Changes smaller than this would print as "0%", so they read as no change.
FLAT_THRESHOLD_PCT = 0.5


class Filters(TypedDict):
    bank: str | None
    category: str | None
    exclude_types: list[str]


class CategoryLabel(TypedDict):
    label: str
    emoji: str


class Trend(TypedDict):
    previous_total: float
    delta_amount: float
    delta_pct: float | None
    direction: str  # up | down | flat | no_data


class CategorySpending(TypedDict):
    category: str | None
    label: str
    emoji: str
    currency: str
    total: float
    trend: Trend | None


class Change(TypedDict):
    category: str | None
    label: str
    delta_amount: float
    direction: str


UNCATEGORIZED: CategoryLabel = {'label': 'Sin categoría', 'emoji': '❔'}

CategoryTotals = dict[tuple[str | None, str], float]


# ── Periods ──────────────────────────────────────────────────────────────────


def _start_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def _shift_months(first_of_month: datetime, months: int) -> datetime:
    index = first_of_month.year * 12 + first_of_month.month - 1 + months
    return first_of_month.replace(year=index // 12, month=index % 12 + 1)


def period_start(period: str, offset: int, local_now: datetime) -> datetime:
    today = _start_of_day(local_now)
    if period == 'today':
        return today + timedelta(days=offset)
    if period == 'week':
        return today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
    return _shift_months(today.replace(day=1), offset)


def period_end(period: str, start: datetime) -> datetime:
    if period == 'today':
        return start + timedelta(days=1)
    if period == 'week':
        return start + timedelta(weeks=1)
    return _shift_months(start, 1)


def resolve_period(period: str, offset: int, local_now: datetime) -> tuple[datetime, datetime]:
    """Half-open local [start, end); the current period ends now."""
    start = period_start(period, offset, local_now)
    return start, min(period_end(period, start), local_now)


def is_closed(period: str, start: datetime, end: datetime) -> bool:
    return end == period_end(period, start)


def previous_range(period: str, start: datetime, end: datetime) -> tuple[datetime, datetime]:
    """The previous period, cut to the same length so far (Mon–Wed vs. last Mon–Wed)."""
    prev_start = period_start(period, -1, start)
    prev_end = period_end(period, prev_start)
    if is_closed(period, start, end):
        return prev_start, prev_end
    return prev_start, min(prev_start + (end - start), prev_end)


def _parse_bound(value: str, tz: ZoneInfo, *, is_end: bool) -> datetime:
    if len(value) == len('YYYY-MM-DD'):
        day = datetime.strptime(value, '%Y-%m-%d').replace(tzinfo=tz)
        return day + timedelta(days=1) if is_end else day
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment + timedelta(seconds=1) if is_end else moment


def resolve_range(
    args: argparse.Namespace, now: datetime, tz: ZoneInfo
) -> tuple[str | None, datetime, datetime]:
    if args.from_date:
        start = _parse_bound(args.from_date, tz, is_end=False)
        end = _parse_bound(args.to_date, tz, is_end=True) if args.to_date else now
        return None, start, end
    period = args.period or 'month'
    start, end = resolve_period(period, args.offset, now.astimezone(tz))
    return period, start, end


def _to_utc(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime(ISO)


# ── Database ─────────────────────────────────────────────────────────────────


def load_timezone(con: sqlite3.Connection) -> ZoneInfo:
    row = con.execute("SELECT value FROM user_settings WHERE key = 'timezone'").fetchone()
    return ZoneInfo(row[0] if row and row[0] else DEFAULT_TIMEZONE)


def load_category_labels(con: sqlite3.Connection) -> dict[str, CategoryLabel]:
    labels: dict[str, CategoryLabel] = {
        slug: {'label': label, 'emoji': DEFAULT_EMOJI}
        for slug, label in con.execute('SELECT slug, label FROM categories')
    }
    labels.update(
        json.loads((SKILL_DIR / 'assets' / 'category_labels.json').read_text(encoding='utf-8'))
    )
    return labels


def _filter_clauses(filters: Filters) -> tuple[list[str], list[str]]:
    where: list[str] = []
    params: list[str] = []
    if filters['bank']:
        where.append('a.bank = ?')
        params.append(filters['bank'])
    if filters['category']:
        where.append('t.category = ?')
        params.append(filters['category'])
    if filters['exclude_types']:
        where.append(
            f't.transaction_type NOT IN ({",".join("?" for _ in filters["exclude_types"])})'
        )
        params.extend(filters['exclude_types'])
    return where, params


def fetch_transactions(
    con: sqlite3.Connection, start: datetime, end: datetime, filters: Filters
) -> list[sqlite3.Row]:
    where, params = _filter_clauses(filters)
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
        WHERE {' AND '.join(['t.date >= ?', 't.date < ?', *where])}
        ORDER BY t.date DESC
    """
    return con.execute(sql, [_to_utc(start), _to_utc(end), *params]).fetchall()


def fetch_income(
    con: sqlite3.Connection, start: datetime, end: datetime, bank: str | None
) -> dict[str, float]:
    sql = f"""
        SELECT t.currency, SUM(t.amount)
        FROM transactions t
        JOIN accounts a ON t.account_id = a.id
        WHERE t.date >= ? AND t.date < ?
          AND t.transaction_type IN ({','.join('?' for _ in INCOME_TYPES)})
          {'AND a.bank = ?' if bank else ''}
        GROUP BY t.currency
    """
    params = [_to_utc(start), _to_utc(end), *INCOME_TYPES, *([bank] if bank else [])]
    return dict(con.execute(sql, params))


def to_transaction(row: sqlite3.Row) -> dict[str, object]:
    return {
        'id': row['id'],
        'amount': row['amount'],
        'currency': row['currency'],
        'merchant': row['merchant'],
        'date': row['date'],
        'transaction_type': row['transaction_type'],
        'channel': row['channel'],
        'category': row['category'],
        'description': row['description'],
        'account': {
            'bank': row['acct_bank'],
            'alias': row['acct_alias'],
            'type': row['acct_type'],
            'masked_number': row['acct_masked'],
        },
        'card': {
            'alias': row['card_alias'],
            'masked_number': row['card_masked'],
            'type': row['card_type'],
        }
        if row['card_masked']
        else None,
    }


# ── Aggregation ──────────────────────────────────────────────────────────────


def totals_by_currency(rows: list[sqlite3.Row]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for r in rows:
        totals[r['currency']] = totals.get(r['currency'], 0.0) + r['amount']
    return totals


def totals_by_category(rows: list[sqlite3.Row]) -> CategoryTotals:
    totals: CategoryTotals = {}
    for r in rows:
        key = (r['category'], r['currency'])
        totals[key] = totals.get(key, 0.0) + r['amount']
    return totals


def spending_trend(current_total: float, previous_total: float) -> Trend:
    delta_amount = current_total - previous_total
    if previous_total == 0:
        return {
            'previous_total': 0.0,
            'delta_amount': delta_amount,
            'delta_pct': None,
            'direction': 'no_data',
        }
    delta_pct = round(delta_amount / previous_total * 100, 1) + 0.0  # + 0.0 turns -0.0 into 0.0
    # Kept as a block: the equivalent nested ternary would exceed the line length.
    if abs(delta_pct) < FLAT_THRESHOLD_PCT:  # noqa: SIM108
        direction = 'flat'
    else:
        direction = 'up' if delta_pct > 0 else 'down'
    return {
        'previous_total': previous_total,
        'delta_amount': delta_amount,
        'delta_pct': delta_pct,
        'direction': direction,
    }


def _label_for(category: str | None, labels: dict[str, CategoryLabel]) -> CategoryLabel:
    if category is None:
        return UNCATEGORIZED
    return labels.get(category, {'label': category.capitalize(), 'emoji': DEFAULT_EMOJI})


def category_spending(
    current: CategoryTotals,
    previous: CategoryTotals | None,
    labels: dict[str, CategoryLabel],
) -> list[CategorySpending]:
    """One entry per (category, currency). With a comparison, categories that only had
    spending in the previous period are included with total 0."""
    entries: list[CategorySpending] = []
    for category, currency in set(current) | set(previous or {}):
        total = current.get((category, currency), 0.0)
        label = _label_for(category, labels)
        entries.append(
            {
                'category': category,
                'label': label['label'],
                'emoji': label['emoji'],
                'currency': currency,
                'total': total,
                'trend': None
                if previous is None
                else spending_trend(total, previous.get((category, currency), 0.0)),
            }
        )
    entries.sort(key=lambda e: (e['currency'], -e['total'], e['label']))
    return entries


def biggest_change(entries: list[CategorySpending]) -> dict[str, Change]:
    """Per currency, the category whose spending moved the most in money terms."""
    changes: dict[str, Change] = {}
    for entry in entries:
        trend = entry['trend']
        if trend is None or trend['direction'] in ('no_data', 'flat'):
            continue
        best = changes.get(entry['currency'])
        if best is None or abs(trend['delta_amount']) > abs(best['delta_amount']):
            changes[entry['currency']] = {
                'category': entry['category'],
                'label': entry['label'],
                'delta_amount': trend['delta_amount'],
                'direction': trend['direction'],
            }
    return changes


# ── Rendering ────────────────────────────────────────────────────────────────


def format_money(amount: float, currency: str) -> str:
    number = f'{amount:,.0f}' if amount == int(amount) else f'{amount:,.2f}'
    return f'${number}' if currency == 'COP' else f'{currency} {number}'


def _money_list(totals: dict[str, float]) -> str:
    return ' · '.join(format_money(total, currency) for currency, total in sorted(totals.items()))


def _trend_suffix(trend: Trend | None, period: str) -> str:
    if trend is None or trend['delta_pct'] is None:
        return ''
    if trend['direction'] == 'flat':
        return '  → igual'
    arrow = '↑' if trend['direction'] == 'up' else '↓'
    return f'  {arrow} {int(abs(trend["delta_pct"]) + 0.5)}% {COMPARISON_BY_PERIOD[period]}'


def _category_lines(entries: list[CategorySpending], period: str) -> str:
    return '\n'.join(
        f'  {e["emoji"]} {e["label"]}: {format_money(e["total"], e["currency"])}'
        f'{_trend_suffix(e["trend"], period)}'
        for e in entries
        if e['total'] > 0
    )


def _change_lines(changes: dict[str, Change]) -> str:
    return '\n'.join(
        f'⚠️ Mayor variación: {c["label"]} {"subió" if c["direction"] == "up" else "bajó"} '
        f'{format_money(abs(c["delta_amount"]), currency)}'
        for currency, c in sorted(changes.items())
    )


def _short_date(dt: datetime) -> str:
    return f'{dt.day} {MONTHS[dt.month - 1][:3]}'


def header_range(period: str, start: datetime, end: datetime) -> str:
    if period == 'month' and is_closed(period, start, end):
        return f'{MONTHS[start.month - 1]} {start.year}'
    last = max(start, end - timedelta(microseconds=1))
    if start.date() == last.date():
        return _short_date(start)
    if start.month == last.month:
        return f'{start.day}–{_short_date(last)}'
    return f'{_short_date(start)} – {_short_date(last)}'


def render_text(
    period: str,
    start: datetime,
    end: datetime,
    spending: dict[str, float],
    entries: list[CategorySpending],
    income: dict[str, float],
    changes: dict[str, Change],
) -> str:
    template = Template(
        (SKILL_DIR / 'templates' / f'{TEMPLATE_BY_PERIOD[period]}.md').read_text(encoding='utf-8')
    )
    text = template.substitute(
        range=header_range(period, start, end),
        spending=f'💸 Total gastado: {_money_list(spending)}'
        if spending
        else '💸 Sin gastos registrados',
        categories=_category_lines(entries, period),
        income=f'📥 Recibido: {_money_list(income)}' if income else '',
        biggest_change=_change_lines(changes),
    )
    return re.sub(r'\n{3,}', '\n\n', text).strip()


# ── Entry ────────────────────────────────────────────────────────────────────


def build_summary(
    con: sqlite3.Connection, args: argparse.Namespace, now: datetime
) -> dict[str, object]:
    con.row_factory = sqlite3.Row
    tz = load_timezone(con)
    period, start, end = resolve_range(args, now, tz)
    filters: Filters = {
        'bank': args.bank,
        'category': args.category,
        'exclude_types': args.exclude_types,
    }
    rows = fetch_transactions(con, start, end, filters)
    spending = totals_by_currency(rows)
    income = fetch_income(con, start, end, args.bank)

    previous, previous_totals = None, None
    if period in TEMPLATE_BY_PERIOD:
        prev_start, prev_end = previous_range(period, start, end)
        prev_rows = fetch_transactions(con, prev_start, prev_end, filters)
        previous_totals = totals_by_category(prev_rows)
        previous = {
            'from': _to_utc(prev_start),
            'to': _to_utc(prev_end),
            'total_by_currency': totals_by_currency(prev_rows),
        }

    entries = category_spending(
        totals_by_category(rows), previous_totals, load_category_labels(con)
    )
    changes = biggest_change(entries)
    text = None
    if period in TEMPLATE_BY_PERIOD:
        text = render_text(period, start, end, spending, entries, income, changes)
    return {
        'transactions': [to_transaction(r) for r in rows],
        'total_by_currency': spending,
        'count': len(rows),
        'from': _to_utc(start),
        'to': _to_utc(end),
        'period': period,
        'timezone': tz.key,
        'spending_by_category': entries,
        'income_by_currency': income,
        'previous': previous,
        'biggest_change': changes,
        'text': text,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--period', choices=['today', 'week', 'month'])
    group.add_argument('--from', dest='from_date', metavar='DATE')
    parser.add_argument('--to', dest='to_date', metavar='DATE')
    parser.add_argument(
        '--offset',
        type=int,
        default=0,
        help='Periods back from the current one: 0 = current, -1 = previous',
    )
    parser.add_argument('--bank', default=None)
    parser.add_argument('--category', default=None)
    parser.add_argument(
        '--exclude-types',
        nargs='+',
        default=['transfer_in', 'credit'],
        help='Transaction types to exclude (default: transfer_in credit — money in)',
    )
    args = parser.parse_args(argv)
    if args.to_date and not args.from_date:
        parser.error('--to requires --from')
    if args.offset > 0 or (args.offset and args.from_date):
        parser.error('--offset must be 0 or negative, and only applies to --period')
    return args


def main() -> None:
    args = parse_args()
    con = sqlite3.connect(DB_PATH)
    summary = build_summary(con, args, datetime.now(UTC))
    con.close()
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
