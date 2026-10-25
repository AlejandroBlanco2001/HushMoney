#!/usr/bin/env python3
"""
debt_tracker eval: record, aggregate (net per person), and settle debts.

No API key required — fully offline.

Covers what the user would notice if it silently regressed:
  - net balance per person (they_owe minus i_owe) is correct
  - person filtering is case-insensitive
  - settling by id and by person removes the right debts and is idempotent

Usage:
    python evals/debt_tracker/debts.py
    python evals/debt_tracker/debts.py -v
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from lib import db as _db, models as _models

REPO_ROOT = _models.REPO_ROOT
RECORD = REPO_ROOT / "skills/debt_tracker/scripts/record_debt.py"
SETTLE = REPO_ROOT / "skills/debt_tracker/scripts/settle_debt.py"
ACTIVE = REPO_ROOT / "skills/debt_tracker/scripts/get_active_debts.py"

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
        print("\ndebt_tracker eval\n")

        joao_they = run(RECORD, "--person", "João", "--amount", "35", "--currency", "USD",
                        "--direction", "they_owe", db_path=db_path, verbose=verbose)
        run(RECORD, "--person", "João", "--amount", "10", "--currency", "USD",
            "--direction", "i_owe", db_path=db_path, verbose=verbose)
        run(RECORD, "--person", "Laura", "--amount", "12000", "--currency", "COP",
            "--direction", "they_owe", "--description", "lunch", db_path=db_path, verbose=verbose)
        check("record_returns_id", joao_they.get("ok") is True and "id" in joao_they, str(joao_they))

        active = run(ACTIVE, db_path=db_path, verbose=verbose)
        check("active_count", active.get("count") == 3, str(active.get("count")))
        summary = active.get("summary", {})
        check("joao_net_they_owe_minus_i_owe", summary.get("João", {}).get("net") == 25.0, str(summary.get("João")))
        check("laura_net", summary.get("Laura", {}).get("net") == 12000.0, str(summary.get("Laura")))

        filtered = run(ACTIVE, "--person", "joão", db_path=db_path, verbose=verbose)
        check("person_filter_case_insensitive", filtered.get("count") == 2, str(filtered.get("count")))

        settled = run(SETTLE, "--id", joao_they["id"], db_path=db_path, verbose=verbose)
        check("settle_by_id_settles_one", settled.get("settled") == 1, str(settled))

        again = run(SETTLE, "--id", joao_they["id"], db_path=db_path, verbose=verbose)
        check("settle_already_settled_is_noop", again.get("settled") == 0, str(again))

        after = run(ACTIVE, "--person", "joão", db_path=db_path, verbose=verbose)
        joao_net_after = after.get("summary", {}).get("João", {}).get("net")
        check("joao_net_after_settle", joao_net_after == -10.0, f"net={joao_net_after}")

        settle_laura = run(SETTLE, "--person", "Laura", "--all", db_path=db_path, verbose=verbose)
        check("settle_person_all", settle_laura.get("settled") == 1, str(settle_laura))

        final = run(ACTIVE, db_path=db_path, verbose=verbose)
        check("one_active_debt_remains", final.get("count") == 1, str(final.get("count")))

        print(f"\n  {_TOTAL - len(_FAILURES)}/{_TOTAL} passed")
        if _FAILURES:
            sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="store_true")
    main(verbose=parser.parse_args().verbose)
