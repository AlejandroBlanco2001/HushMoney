"""
Look up the most common category for a merchant from past transactions.

Usage: python3 lookup_cached_category.py --merchant "UBER"
Output: {"category": "transport", "confidence": 0.95, "sample_count": 12}
        {"category": null}  — if no history or below threshold
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3


DB_PATH = os.environ.get('HUSHMONEY_DB', os.path.expanduser('~/.hermes/hushmoney.db'))
MIN_SAMPLES = 1
MIN_CONFIDENCE = 0.6


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--merchant', required=True)
    args = parser.parse_args()

    con = sqlite3.connect(DB_PATH)
    rows = con.execute(
        """
        SELECT category, COUNT(*) AS cnt
        FROM transactions
        WHERE UPPER(merchant) = UPPER(?) AND category IS NOT NULL
        GROUP BY category
        ORDER BY cnt DESC
        """,
        (args.merchant,),
    ).fetchall()
    con.close()

    if not rows:
        print(json.dumps({"category": None}))
        return

    top_category, top_count = rows[0]
    total = sum(r[1] for r in rows)
    confidence = top_count / total

    if top_count < MIN_SAMPLES or confidence < MIN_CONFIDENCE:
        print(json.dumps({"category": None}))
        return

    print(json.dumps({
        "category": top_category,
        "confidence": round(confidence, 2),
        "sample_count": total,
    }))


if __name__ == '__main__':
    main()
