#!/usr/bin/env python3
"""
Cache lookup eval: verifies lookup_cached_category.py behavior against known DB state.

No API key required — this eval is fully offline.

Tests three scenarios:
  1. Known merchant, unambiguous  → found=true, correct category, needs_clarification=false
  2. Known merchant, ambiguous    → found=true, needs_clarification=true, last_category preserved
  3. Unknown merchant             → found=false
  4. Fallback (no merchants row, but transaction history) → found=true from frequency analysis

Usage:
    python evals/categorizer/cache_lookup.py
    python evals/categorizer/cache_lookup.py -v   # verbose: print each script invocation
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
from typing import Any


sys.path.insert(0, str(Path(__file__).parent.parent))
from lib import db as _db
from lib import models as _models


REPO_ROOT = _models.REPO_ROOT
SCRIPT = REPO_ROOT / 'skills/categorizer/scripts/lookup_cached_category.py'


# ── DB setup ───────────────────────────────────────────────────────────────────


def _seed_db(db_path: str) -> None:
    con = sqlite3.connect(db_path)
    now = '2026-01-01T00:00:00+00:00'

    # Seed merchants
    con.execute(
        'INSERT INTO merchants (name, category, needs_clarification, last_category, is_recurring, created_at, updated_at)'
        ' VALUES (?, ?, ?, ?, ?, ?, ?)',
        ('NETFLIX', 'entertainment', 0, None, 1, now, now),
    )
    con.execute(
        'INSERT INTO merchants (name, category, needs_clarification, last_category, is_recurring, created_at, updated_at)'
        ' VALUES (?, ?, ?, ?, ?, ?, ?)',
        ('UBER RIDES', 'transport', 0, None, 0, now, now),
    )
    con.execute(
        'INSERT INTO merchants (name, category, needs_clarification, last_category, is_recurring, created_at, updated_at)'
        ' VALUES (?, ?, ?, ?, ?, ?, ?)',
        ('RAPPI', None, 1, 'food', 0, now, now),
    )
    con.execute(
        'INSERT INTO merchants (name, category, needs_clarification, last_category, is_recurring, created_at, updated_at)'
        ' VALUES (?, ?, ?, ?, ?, ?, ?)',
        ('PEXTO CAPITAL SAS', None, 1, None, 0, now, now),
    )

    # Seed an account + transactions for the fallback test (no merchants row for "MCD")
    con.execute(
        'INSERT INTO accounts (id, bank, type, currency, created_at) VALUES (?, ?, ?, ?, ?)',
        ('acc-1', 'bancolombia', 'checking', 'COP', now),
    )
    for i in range(4):
        con.execute(
            'INSERT INTO transactions (id, account_id, amount, currency, merchant, date,'
            ' transaction_type, channel, category, message_hash, created_at, updated_at)'
            ' VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (
                f'tx-mcd-{i}',
                'acc-1',
                28000,
                'COP',
                'MCD',
                '2026-01-01',
                'debit',
                'sms',
                'food',
                f'hash-mcd-{i}',
                now,
                now,
            ),
        )

    con.commit()
    con.close()


# ── Cases ──────────────────────────────────────────────────────────────────────


@dataclass
class Case:
    name: str
    merchant: str
    expect_found: bool
    expect_needs_clarification: bool
    expect_category: str | None  # None means "don't check"
    expect_last_category: str | None  # None means "don't check"
    expect_is_recurring: bool | None  # None means "don't check"
    description: str


CASES: list[Case] = [
    Case(
        name='netflix_cache_hit',
        merchant='NETFLIX',
        expect_found=True,
        expect_needs_clarification=False,
        expect_category='entertainment',
        expect_last_category=None,
        expect_is_recurring=True,
        description='Known recurring merchant → is_recurring=true',
    ),
    Case(
        name='uber_rides_cache_hit',
        merchant='UBER RIDES',
        expect_found=True,
        expect_needs_clarification=False,
        expect_category='transport',
        expect_last_category=None,
        expect_is_recurring=False,
        description='Non-recurring merchant → is_recurring=false',
    ),
    Case(
        name='rappi_needs_clarification',
        merchant='RAPPI',
        expect_found=True,
        expect_needs_clarification=True,
        expect_category=None,
        expect_last_category='food',
        expect_is_recurring=None,
        description='Known ambiguous merchant → needs_clarification with last_category hint',
    ),
    Case(
        name='pexto_needs_clarification_no_hint',
        merchant='PEXTO CAPITAL SAS',
        expect_found=True,
        expect_needs_clarification=True,
        expect_category=None,
        expect_last_category=None,
        expect_is_recurring=None,
        description='Known ambiguous merchant with no prior category',
    ),
    Case(
        name='unknown_merchant_miss',
        merchant='ALKOSTO',
        expect_found=False,
        expect_needs_clarification=False,
        expect_category=None,
        expect_last_category=None,
        expect_is_recurring=None,
        description='Completely unknown merchant → cache miss',
    ),
    Case(
        name='case_insensitive_lookup',
        merchant='netflix',
        expect_found=True,
        expect_needs_clarification=False,
        expect_category='entertainment',
        expect_last_category=None,
        expect_is_recurring=True,
        description='Case-insensitive lookup preserves is_recurring flag',
    ),
    Case(
        name='whitespace_normalization',
        merchant='  UBER   RIDES  ',
        expect_found=True,
        expect_needs_clarification=False,
        expect_category='transport',
        expect_last_category=None,
        expect_is_recurring=None,
        description='Extra whitespace is normalized before lookup',
    ),
    Case(
        name='fallback_transaction_history',
        merchant='MCD',
        expect_found=True,
        expect_needs_clarification=False,
        expect_category='food',
        expect_last_category=None,
        expect_is_recurring=None,
        description='No merchants row but 4 matching transactions → fallback finds food',
    ),
]


# ── Runner ─────────────────────────────────────────────────────────────────────


def run_case(case: Case, db_path: str, verbose: bool) -> tuple[bool, str]:
    env = {**os.environ, 'HUSHMONEY_DB': db_path}
    cmd = [sys.executable, str(SCRIPT), '--merchant', case.merchant]

    if verbose:
        print(f"    $ HUSHMONEY_DB={db_path} python3 {SCRIPT.name} --merchant '{case.merchant}'")

    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        return False, f'script exited {proc.returncode}: {proc.stderr.strip()}'

    try:
        result: dict[str, Any] = json.loads(proc.stdout.strip())
    except json.JSONDecodeError:
        return False, f'invalid JSON output: {proc.stdout!r}'

    if verbose:
        print(f'    → {result}')

    failures = []

    if result.get('found') != case.expect_found:
        failures.append(f'found={result.get("found")} want {case.expect_found}')

    if result.get('needs_clarification') != case.expect_needs_clarification:
        failures.append(
            f'needs_clarification={result.get("needs_clarification")} want {case.expect_needs_clarification}'
        )

    if case.expect_category is not None and result.get('category') != case.expect_category:
        failures.append(f'category={result.get("category")!r} want {case.expect_category!r}')

    if (
        case.expect_last_category is not None
        and result.get('last_category') != case.expect_last_category
    ):
        failures.append(
            f'last_category={result.get("last_category")!r} want {case.expect_last_category!r}'
        )

    if (
        case.expect_is_recurring is not None
        and result.get('is_recurring') != case.expect_is_recurring
    ):
        failures.append(
            f'is_recurring={result.get("is_recurring")} want {case.expect_is_recurring}'
        )

    if failures:
        return False, '; '.join(failures)
    return True, ''


def main(verbose: bool = False) -> None:
    with _db.temp_db() as db_path:
        _seed_db(db_path)

        passed = 0
        failed = 0

        print(f'\nCache lookup eval  ({len(CASES)} cases)\n')

        for case in CASES:
            ok, detail = run_case(case, db_path, verbose)
            mark = '✓' if ok else '✗'
            print(f'  {mark} {case.name:<42} {case.description}')
            if not ok:
                print(f'      FAIL: {detail}')
                failed += 1
            else:
                passed += 1
            if verbose:
                print()

        print(f'\n  {passed}/{len(CASES)} passed', end='')
        if failed:
            print(f'  ({failed} failed)')
            sys.exit(1)
        else:
            print()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', '--verbose', action='store_true')
    args = parser.parse_args()
    main(verbose=args.verbose)
