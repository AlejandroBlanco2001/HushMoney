#!/usr/bin/env python3
"""
expense_tracker eval: store_transaction insert/dedup + account reuse, and check_duplicate.

No API key required — fully offline.

Covers the things that silently corrupt a user's ledger:
  - a transaction is stored exactly once (idempotent on message_hash)
  - a repeated notification does not double-count
  - one account row is reused across transactions for the same (bank, type, currency)
  - check_duplicate reflects stored hashes

Usage:
    python evals/expense_tracker/store_and_dedup.py
    python evals/expense_tracker/store_and_dedup.py -v
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from lib import db as _db, models as _models

REPO_ROOT = _models.REPO_ROOT
STORE = REPO_ROOT / "skills/expense_tracker/scripts/store_transaction.py"
CHECK = REPO_ROOT / "skills/expense_tracker/scripts/check_duplicate.py"

_BASE = [
    "--currency", "COP", "--date", "2026-10-21T09:56:00Z",
    "--transaction-type", "debit", "--account-type", "checking",
    "--channel", "sms", "--bank", "bancolombia",
]

_TOTAL = 0
_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global _TOTAL
    _TOTAL += 1
    print(f"  {'✓' if cond else '✗'} {name}" + ("" if cond else f"  — {detail}"))
    if not cond:
        _FAILURES.append(name)


def run(script: Path, *args: str, db_path: str, verbose: bool = False) -> dict:
    env = {**os.environ, "HUSHMONEY_DB": db_path}
    if verbose:
        print(f"    $ {script.name} {' '.join(args)}")
    proc = subprocess.run(
        [sys.executable, str(script), *args], capture_output=True, text=True, env=env
    )
    if proc.returncode != 0:
        return {"_error": proc.stderr.strip()}
    try:
        out = json.loads(proc.stdout.strip())
    except json.JSONDecodeError:
        return {"_error": f"invalid JSON: {proc.stdout!r}"}
    if verbose:
        print(f"    → {out}")
    return out


def main(verbose: bool = False) -> None:
    with _db.temp_db() as db_path:
        print("\nexpense_tracker store/dedup eval\n")

        first = run(STORE, "--amount", "6930", "--merchant", "UBER", *_BASE, db_path=db_path, verbose=verbose)
        check("first_insert_ok", first.get("ok") is True and first.get("duplicate") is False and "id" in first, str(first))

        repeat = run(STORE, "--amount", "6930", "--merchant", "UBER", *_BASE, db_path=db_path, verbose=verbose)
        check("duplicate_notification_skipped", repeat.get("duplicate") is True, str(repeat))

        distinct = run(STORE, "--amount", "12000", "--merchant", "RAPPI", *_BASE, db_path=db_path, verbose=verbose)
        check("distinct_payload_inserts", distinct.get("duplicate") is False and "id" in distinct, str(distinct))

        con = sqlite3.connect(db_path)
        n_accounts = con.execute(
            "SELECT COUNT(*) FROM accounts WHERE bank='bancolombia' AND type='checking' AND currency='COP'"
        ).fetchone()[0]
        n_tx = con.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        con.close()
        check("account_find_or_create_reuse", n_accounts == 1, f"accounts={n_accounts}")
        check("two_transactions_stored", n_tx == 2, f"transactions={n_tx}")

        h1 = run(STORE, "--amount", "500", "--message-hash", "deadbeef", *_BASE, db_path=db_path, verbose=verbose)
        h2 = run(STORE, "--amount", "999", "--message-hash", "deadbeef", *_BASE, db_path=db_path, verbose=verbose)
        check("explicit_hash_dedup", h1.get("duplicate") is False and h2.get("duplicate") is True, f"{h1} {h2}")

        dup = run(CHECK, "--hash", "deadbeef", db_path=db_path, verbose=verbose)
        miss = run(CHECK, "--hash", "nothere", db_path=db_path, verbose=verbose)
        check("check_duplicate_true", dup.get("duplicate") is True, str(dup))
        check("check_duplicate_false", miss.get("duplicate") is False, str(miss))

        print(f"\n  {_TOTAL - len(_FAILURES)}/{_TOTAL} passed")
        if _FAILURES:
            sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="store_true")
    main(verbose=parser.parse_args().verbose)
