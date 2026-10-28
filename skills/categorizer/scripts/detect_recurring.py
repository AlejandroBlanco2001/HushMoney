"""
Detect whether a merchant charges recurringly based on transaction history.

A merchant is considered recurring when transactions appear in ≥ MIN_MONTHS distinct
calendar months AND the day-of-month is within DAY_TOLERANCE days of the median
charge day across those months.

Days 28–31 are normalized to 28 so end-of-month subscriptions (e.g. charged "the
last day of the month") are treated consistently regardless of month length.

Usage: python3 detect_recurring.py --merchant "NETFLIX"
Output: {"is_recurring": true,  "months_found": 6, "median_day": 15}
        {"is_recurring": false, "months_found": 2}
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3


DB_PATH = os.environ.get('HUSHMONEY_DB', os.path.expanduser('~/.hermes/hushmoney.db'))

MIN_MONTHS = 4
DAY_TOLERANCE = 3


def _normalize_day(dom: int) -> int:
    return min(dom, 28)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--merchant', required=True)
    args = parser.parse_args()

    name = ' '.join(args.merchant.split()).upper()

    con = sqlite3.connect(DB_PATH)
    rows = con.execute(
        """
        SELECT
            CAST(strftime('%d', date) AS INTEGER) AS dom,
            strftime('%Y-%m', date)               AS month
        FROM transactions
        WHERE UPPER(merchant) = ?
          AND category IS NOT NULL
          AND transaction_type NOT IN ('transfer_in', 'transfer_out', 'cash')
        ORDER BY date
        """,
        (name,),
    ).fetchall()
    con.close()

    # One entry per calendar month (earliest transaction in that month).
    seen: dict[str, int] = {}
    for dom, month in rows:
        if month not in seen:
            seen[month] = _normalize_day(dom)

    months_found = len(seen)
    if months_found < MIN_MONTHS:
        print(json.dumps({'is_recurring': False, 'months_found': months_found}))
        return

    days = sorted(seen.values())
    median_day = days[len(days) // 2]
    consistent = sum(1 for d in days if abs(d - median_day) <= DAY_TOLERANCE)

    is_recurring = consistent >= MIN_MONTHS
    print(
        json.dumps(
            {
                'is_recurring': is_recurring,
                'months_found': months_found,
                'median_day': median_day,
                'consistent_months': consistent,
            }
        )
    )


if __name__ == '__main__':
    main()
