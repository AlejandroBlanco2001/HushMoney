"""
Look up the category for a merchant from the merchants cache table.
Falls back to transaction frequency analysis for merchants predating the cache.

Usage: python3 lookup_cached_category.py --merchant "UBER RIDES"
Output (cache hit, unambiguous):  {"found": true, "category": "transport", "needs_clarification": false}
Output (cache hit, ambiguous):    {"found": true, "category": null, "needs_clarification": true, "last_category": "food"}
Output (cache miss):              {"found": false, "category": null, "needs_clarification": false}
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3


DB_PATH = os.environ.get('HUSHMONEY_DB', os.path.expanduser('~/.hermes/hushmoney.db'))

# Minimum samples / confidence for the transaction-history fallback.
_MIN_SAMPLES = 3
_MIN_CONFIDENCE = 0.75


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--merchant', required=True)
    args = parser.parse_args()

    name = ' '.join(args.merchant.split()).upper()

    con = sqlite3.connect(DB_PATH)

    # 1. Check dedicated merchants cache first.
    row = con.execute(
        'SELECT category, needs_clarification, last_category, COALESCE(is_recurring, 0) FROM merchants WHERE name = ?',
        (name,),
    ).fetchone()

    if row is not None:
        con.close()
        category, needs_clarification, last_category, is_recurring = row
        print(
            json.dumps(
                {
                    'found': True,
                    'category': category,
                    'needs_clarification': bool(needs_clarification),
                    'last_category': last_category,
                    'is_recurring': bool(is_recurring),
                }
            )
        )
        return

    # 2. Fallback: frequency analysis on past transactions (for rows predating the cache).
    rows = con.execute(
        """
        SELECT category, COUNT(*) AS cnt
        FROM transactions
        WHERE UPPER(merchant) = ? AND category IS NOT NULL
        GROUP BY category
        ORDER BY cnt DESC
        """,
        (name,),
    ).fetchall()
    con.close()

    if not rows:
        print(
            json.dumps(
                {
                    'found': False,
                    'category': None,
                    'needs_clarification': False,
                    'is_recurring': False,
                }
            )
        )
        return

    top_category, top_count = rows[0]
    total = sum(r[1] for r in rows)
    confidence = top_count / total

    if top_count < _MIN_SAMPLES or confidence < _MIN_CONFIDENCE:
        print(
            json.dumps(
                {
                    'found': False,
                    'category': None,
                    'needs_clarification': False,
                    'is_recurring': False,
                }
            )
        )
        return

    print(
        json.dumps(
            {
                'found': True,
                'category': top_category,
                'needs_clarification': False,
                'last_category': None,
                'is_recurring': False,
            }
        )
    )


if __name__ == '__main__':
    main()
