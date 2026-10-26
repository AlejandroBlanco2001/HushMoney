#!/usr/bin/env python3
"""
summaries eval: query_transactions period/filter correctness and totals.

No API key required — fully offline. (Summary *text* quality is a separate,
token-costing LLM-as-judge eval; this guards the numbers the judge would read.)

Covers what the user would notice if it silently regressed:
  - date-range filtering excludes out-of-range transactions
  - transfer_in is excluded by default (not spending)
  - bank and category filters narrow correctly
  - total_by_currency sums per currency
  - account/card context is joined onto each row

Usage:
    python evals/summaries/query.py
    python evals/summaries/query.py -v
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
QUERY = REPO_ROOT / "skills/summaries/scripts/query_transactions.py"
NOW = "2026-01-01T00:00:00+00:00"

_TOTAL = 0
_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global _TOTAL
    _TOTAL += 1
    print(f"  {'✓' if cond else '✗'} {name}" + ("" if cond else f"  — {detail}"))
    if not cond:
        _FAILURES.append(name)


def _seed(db_path: str) -> None:
    con = sqlite3.connect(db_path)
    con.execute(
        "INSERT INTO accounts (id, bank, alias, type, currency, masked_number, created_at)"
        " VALUES ('acc-co', 'bancolombia', 'Ahorros', 'checking', 'COP', '****1234', ?)", (NOW,)
    )
    con.execute(
        "INSERT INTO accounts (id, bank, type, currency, created_at)"
        " VALUES ('acc-us', 'davivienda', 'savings', 'USD', ?)", (NOW,)
    )
    con.execute(
        "INSERT INTO cards (id, account_id, type, masked_number, alias, created_at)"
        " VALUES ('card-1', 'acc-co', 'debit', '****5678', 'Visa', ?)", (NOW,)
    )
    # (id, account, card, amount, currency, merchant, date, type, channel, category)
    rows = [
        ("t1", "acc-co", "card-1", 10000, "COP", "EXITO", "2026-10-05T12:00:00Z", "debit", "food"),
        ("t2", "acc-co", None, 5000, "COP", "UBER", "2026-10-10T12:00:00Z", "debit", "transport"),
        ("t3", "acc-us", None, 20, "USD", "STEAM", "2026-10-12T12:00:00Z", "debit", "food"),
        ("t4", "acc-co", None, 99999, "COP", None, "2026-10-15T12:00:00Z", "transfer_in", "transfers"),
        ("t5", "acc-co", None, 7000, "COP", "OLD", "2026-09-01T12:00:00Z", "debit", "food"),
    ]
    for tid, acc, card, amt, cur, merch, date, ttype, cat in rows:
        con.execute(
            "INSERT INTO transactions"
            " (id, account_id, card_id, amount, currency, merchant, date,"
            "  transaction_type, channel, category, message_hash, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'sms', ?, ?, ?, ?)",
            (tid, acc, card, amt, cur, merch, date, ttype, cat, f"h-{tid}", NOW, NOW),
        )
    con.commit()
    con.close()


def run(*args: str, db_path: str, verbose: bool = False) -> dict:
    env = {**os.environ, "HUSHMONEY_DB": db_path}
    if verbose:
        print(f"    $ query_transactions.py {' '.join(args)}")
    proc = subprocess.run(
        [sys.executable, str(QUERY), *args], capture_output=True, text=True, env=env
    )
    if proc.returncode != 0:
        return {"_error": proc.stderr.strip()}
    try:
        out = json.loads(proc.stdout.strip())
    except json.JSONDecodeError:
        return {"_error": f"invalid JSON: {proc.stdout!r}"}
    if verbose:
        print(f"    → count={out.get('count')} totals={out.get('total_by_currency')}")
    return out


def main(verbose: bool = False) -> None:
    with _db.temp_db() as db_path:
        _seed(db_path)
        print("\nsummaries query_transactions eval\n")
        rng = ["--from", "2026-10-01", "--to", "2026-10-31T23:59:59Z"]

        base = run(*rng, db_path=db_path, verbose=verbose)
        # t4 excluded (transfer_in), t5 excluded (out of range) → t1, t2, t3
        check("range_and_transfer_in_excluded", base.get("count") == 3, str(base.get("count")))
        check("total_by_currency", base.get("total_by_currency") == {"COP": 15000.0, "USD": 20.0},
              str(base.get("total_by_currency")))

        by_id = {t["id"]: t for t in base.get("transactions", [])}
        check("account_context_joined", by_id.get("t1", {}).get("account", {}).get("bank") == "bancolombia",
              str(by_id.get("t1", {}).get("account")))
        check("card_context_joined", (by_id.get("t1", {}).get("card") or {}).get("masked_number") == "****5678",
              str(by_id.get("t1", {}).get("card")))
        check("no_card_is_null", by_id.get("t2", {}).get("card") is None, str(by_id.get("t2", {}).get("card")))

        bank = run(*rng, "--bank", "bancolombia", db_path=db_path, verbose=verbose)
        check("bank_filter", bank.get("count") == 2 and bank.get("total_by_currency") == {"COP": 15000.0},
              str(bank.get("total_by_currency")))

        cat = run(*rng, "--category", "food", db_path=db_path, verbose=verbose)
        check("category_filter", cat.get("count") == 2 and cat.get("total_by_currency") == {"COP": 10000.0, "USD": 20.0},
              str(cat.get("total_by_currency")))

        # Override exclusion to keep only transfer_in in range → just t4.
        only_transfer = run(*rng, "--exclude-types", "debit", db_path=db_path, verbose=verbose)
        check("exclude_types_override", only_transfer.get("count") == 1 and only_transfer.get("total_by_currency") == {"COP": 99999.0},
              str(only_transfer.get("total_by_currency")))

        print(f"\n  {_TOTAL - len(_FAILURES)}/{_TOTAL} passed")
        if _FAILURES:
            sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="store_true")
    main(verbose=parser.parse_args().verbose)
