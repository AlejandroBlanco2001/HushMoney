"""
Return the spending category list.

Reads from the categories table in SQLite. Falls back to the hardcoded default
list if the table is empty or unavailable (e.g. before first migration).

Output: {"categories": [{"slug": "food", "label": "Food & Dining", "description": "..."}]}
"""

from __future__ import annotations

import json
import os
import sqlite3


DB_PATH = os.environ.get('HUSHMONEY_DB', os.path.expanduser('~/.hermes/hushmoney.db'))

_DEFAULT_CATEGORIES = [
    {
        'slug': 'food',
        'label': 'Food & Dining',
        'description': 'Restaurants, cafes, supermarkets, food delivery',
    },
    {
        'slug': 'transport',
        'label': 'Transport',
        'description': 'Ride-hailing, taxis, fuel, parking, public transit',
    },
    {
        'slug': 'entertainment',
        'label': 'Entertainment',
        'description': 'Streaming, gaming, cinema, concerts, events',
    },
    {'slug': 'health', 'label': 'Health', 'description': 'Pharmacies, clinics, hospitals, gyms'},
    {
        'slug': 'shopping',
        'label': 'Shopping',
        'description': 'Clothing, electronics, online marketplaces',
    },
    {
        'slug': 'services',
        'label': 'Services & Utilities',
        'description': 'Telecom, utilities, insurance, rent',
    },
    {
        'slug': 'transfers',
        'label': 'Transfers',
        'description': 'Bank transfers, peer-to-peer payments',
    },
    {'slug': 'cash', 'label': 'Cash Withdrawal', 'description': 'ATM withdrawals'},
    {'slug': 'other', 'label': 'Other', 'description': 'Uncategorized or one-off expenses'},
]


def main() -> None:
    try:
        con = sqlite3.connect(DB_PATH)
        rows = con.execute(
            'SELECT slug, label, description FROM categories ORDER BY slug'
        ).fetchall()
        con.close()
        if rows:
            cats = [{'slug': r[0], 'label': r[1], 'description': r[2]} for r in rows]
            print(json.dumps({'categories': cats}))
            return
    except Exception:  # noqa: S110  # best-effort DB read; falls through to defaults below
        pass

    print(json.dumps({'categories': _DEFAULT_CATEGORIES}))


if __name__ == '__main__':
    main()
