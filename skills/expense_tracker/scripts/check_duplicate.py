"""
Check whether a message_hash already exists in the transactions table.
Usage: python3 check_duplicate.py --hash <sha256_hex>
Output: {"duplicate": true|false}
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3


DB_PATH = os.environ.get('HUSHMONEY_DB', os.path.expanduser('~/.hermes/hushmoney.db'))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--hash', required=True, help='SHA-256 hex of the message fingerprint')
    args = parser.parse_args()

    con = sqlite3.connect(DB_PATH)
    row = con.execute(
        'SELECT 1 FROM transactions WHERE message_hash = ? LIMIT 1', (args.hash,)
    ).fetchone()
    con.close()

    print(json.dumps({'duplicate': row is not None}))


if __name__ == '__main__':
    main()
