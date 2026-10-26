#!/usr/bin/env python3
"""
Eval for detect_recurring.py — verifies the recurring-detection heuristic
against seeded transaction histories.

No API key required — fully offline.

Usage:
    python evals/categorizer/recurring.py
    python evals/categorizer/recurring.py -v
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from lib import db as _db, models as _models

REPO_ROOT = _models.REPO_ROOT
SCRIPT = REPO_ROOT / "skills/categorizer/scripts/detect_recurring.py"


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _insert_transactions(db_path: str, merchant: str, charges: list[tuple[str, float]]) -> None:
    """Insert one transaction per (date, amount) pair for a merchant."""
    con = sqlite3.connect(db_path)
    now = "2026-01-01T00:00:00+00:00"
    con.execute(
        "INSERT OR IGNORE INTO accounts (id, bank, type, currency, created_at)"
        " VALUES ('acc-1', 'bancolombia', 'checking', 'COP', ?)", (now,)
    )
    with con:
        for i, (date, amount) in enumerate(charges):
            con.execute(
                "INSERT INTO transactions"
                " (id, account_id, amount, currency, merchant, date,"
                "  transaction_type, channel, category, message_hash, created_at, updated_at)"
                " VALUES (?, 'acc-1', ?, 'COP', ?, ?, 'debit', 'sms', 'entertainment', ?, ?, ?)",
                (f"tx-{merchant}-{i}", amount, merchant, date, f"hash-{merchant}-{i}", now, now),
            )
    con.close()


# ── Cases ──────────────────────────────────────────────────────────────────────

@dataclass
class Case:
    name: str
    merchant: str
    charges: list[tuple[str, float]]   # (ISO date, amount)
    expect_recurring: bool
    description: str


CASES: list[Case] = [
    Case(
        name="six_months_same_day",
        merchant="NETFLIX-A",
        charges=[
            ("2026-01-15", 17900), ("2026-02-15", 17900), ("2026-03-15", 17900),
            ("2026-04-15", 17900), ("2026-05-15", 17900), ("2026-06-15", 17900),
        ],
        expect_recurring=True,
        description="6 months, identical day → recurring",
    ),
    Case(
        name="exactly_four_months",
        merchant="SPOTIFY-A",
        charges=[
            ("2026-01-01", 14900), ("2026-02-01", 14900),
            ("2026-03-01", 14900), ("2026-04-01", 14900),
        ],
        expect_recurring=True,
        description="Exactly 4 months at threshold → recurring",
    ),
    Case(
        name="three_months_below_threshold",
        merchant="BODYTECH-A",
        charges=[
            ("2026-01-05", 89900), ("2026-02-05", 89900), ("2026-03-05", 89900),
        ],
        expect_recurring=False,
        description="Only 3 months — below MIN_MONTHS → not recurring",
    ),
    Case(
        name="four_months_within_tolerance",
        merchant="CLARO-A",
        charges=[
            ("2026-01-03", 55000), ("2026-02-01", 55000),
            ("2026-03-04", 55000), ("2026-04-02", 55000),
        ],
        expect_recurring=True,
        description="4 months, days 1–4 (all within ±3 of median 2) → recurring",
    ),
    Case(
        name="days_too_spread",
        merchant="RANDOM-A",
        charges=[
            ("2026-01-01", 50000), ("2026-02-15", 50000),
            ("2026-03-20", 50000), ("2026-04-28", 50000),
        ],
        expect_recurring=False,
        description="4 months but charges on days 1, 15, 20, 28 — too spread → not recurring",
    ),
    Case(
        name="end_of_month_normalization",
        merchant="INSURANCE-A",
        charges=[
            ("2026-01-31", 120000), ("2026-02-28", 120000),
            ("2026-03-31", 120000), ("2026-04-30", 120000),
        ],
        expect_recurring=True,
        description="End-of-month charges (31, 28, 31, 30) normalized to 28 → recurring",
    ),
    Case(
        name="multiple_per_month_uses_first",
        merchant="AMAZON-A",
        charges=[
            ("2026-01-10", 35000), ("2026-01-25", 12000),  # two in January
            ("2026-02-11", 35000),
            ("2026-03-10", 35000),
            ("2026-04-09", 35000),
        ],
        expect_recurring=True,
        description="Multiple charges per month — only first used per month, 4 months match → recurring",
    ),
    Case(
        name="transfers_excluded",
        merchant="NEQUI-A",
        charges=[],  # seeded separately with transfer_in type
        expect_recurring=False,
        description="transfer_in transactions excluded from recurring detection",
    ),
    Case(
        name="no_transactions",
        merchant="UNKNOWN-MERCHANT",
        charges=[],
        expect_recurring=False,
        description="No transaction history → not recurring",
    ),
]


def _seed_transfers(db_path: str) -> None:
    """Seed transfer_in transactions for NEQUI-A — should be excluded."""
    con = sqlite3.connect(db_path)
    now = "2026-01-01T00:00:00+00:00"
    con.execute(
        "INSERT OR IGNORE INTO accounts (id, bank, type, currency, created_at)"
        " VALUES ('acc-1', 'bancolombia', 'checking', 'COP', ?)", (now,)
    )
    with con:
        for i, date in enumerate(["2026-01-05", "2026-02-05", "2026-03-05", "2026-04-05"]):
            con.execute(
                "INSERT INTO transactions"
                " (id, account_id, amount, currency, merchant, date,"
                "  transaction_type, channel, category, message_hash, created_at, updated_at)"
                " VALUES (?, 'acc-1', 80000, 'COP', 'NEQUI-A', ?, 'transfer_in', 'sms', 'transfers', ?, ?, ?)",
                (f"tx-nequi-{i}", date, f"hash-nequi-{i}", now, now),
            )
    con.close()


# ── Runner ─────────────────────────────────────────────────────────────────────

def run_case(case: Case, db_path: str, verbose: bool) -> tuple[bool, str]:
    env = {**os.environ, "HUSHMONEY_DB": db_path}
    cmd = [sys.executable, str(SCRIPT), "--merchant", case.merchant]

    if verbose:
        print(f"    $ python3 {SCRIPT.name} --merchant '{case.merchant}'")

    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        return False, f"script exited {proc.returncode}: {proc.stderr.strip()}"

    try:
        result = json.loads(proc.stdout.strip())
    except json.JSONDecodeError:
        return False, f"invalid JSON: {proc.stdout!r}"

    if verbose:
        print(f"    → {result}")

    got = result.get("is_recurring")
    if got != case.expect_recurring:
        months = result.get("months_found", "?")
        median = result.get("median_day", "?")
        consistent = result.get("consistent_months", "?")
        return False, (
            f"is_recurring={got} want {case.expect_recurring} "
            f"(months={months}, median_day={median}, consistent={consistent})"
        )

    return True, ""


def main(verbose: bool = False) -> None:
    with _db.temp_db() as db_path:
        for case in CASES:
            if case.charges:
                _insert_transactions(db_path, case.merchant, case.charges)
        _seed_transfers(db_path)

        passed = 0
        failed = 0

        print(f"\nRecurring detection eval  ({len(CASES)} cases)\n")

        for case in CASES:
            ok, detail = run_case(case, db_path, verbose)
            mark = "✓" if ok else "✗"
            print(f"  {mark} {case.name:<40} {case.description}")
            if not ok:
                print(f"      FAIL: {detail}")
                failed += 1
            else:
                passed += 1
            if verbose:
                print()

        print(f"\n  {passed}/{len(CASES)} passed", end="")
        if failed:
            print(f"  ({failed} failed)")
            sys.exit(1)
        else:
            print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    main(verbose=args.verbose)
