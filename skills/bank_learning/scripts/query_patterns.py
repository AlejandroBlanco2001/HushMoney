"""
Query learned patterns for a bank + channel.

Usage: python3 query_patterns.py --bank davivienda --channel sms
Output: {"patterns": [...], "count": N}
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3


DB_PATH = os.environ.get('HUSHMONEY_DB', os.path.expanduser('~/.hermes/hushmoney.db'))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--bank', required=True)
    parser.add_argument('--channel', required=True, choices=['sms', 'email'])
    args = parser.parse_args()

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """SELECT id, bank_slug, country, channel, pattern, confirmed, uses, created_at
           FROM learned_patterns
           WHERE bank_slug = ? AND channel = ? AND active = 1
           ORDER BY confirmed DESC, uses DESC""",
        (args.bank, args.channel),
    ).fetchall()
    con.close()

    print(json.dumps({'patterns': [dict(r) for r in rows], 'count': len(rows)}))


if __name__ == '__main__':
    main()
