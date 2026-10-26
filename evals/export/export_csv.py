#!/usr/bin/env python3
"""
export eval: export_csv period filtering, CSV columns and signed amounts.

No API key required — fully offline.

Covers what the user would notice if it silently regressed:
  - the CSV has exactly the documented columns, in order
  - spending is negative, income (transfer_in, credit) is positive
  - --month / --from-to include only rows in range (inclusive end day)
  - no internal ids, message hashes or card numbers leak into the file
  - formula-looking merchant names are neutralised, and every cell is quoted so
    a separator inside a value cannot start a new formula cell (OWASP CSV injection)
  - an empty period writes no file, and each run clears the previous export

Usage:
    python evals/export/export_csv.py
    python evals/export/export_csv.py -v
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from lib import db as _db, models as _models

EXPORT = _models.REPO_ROOT / "skills/export/scripts/export_csv.py"
NOW = "2026-01-01T00:00:00+00:00"
COLUMNS = ["date", "merchant", "amount", "currency", "category",
           "transaction_type", "account", "channel"]

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
    _db.seed_categories(db_path)
    con.execute(
        "INSERT INTO accounts (id, bank, alias, type, currency, masked_number, created_at)"
        " VALUES ('acc-co', 'bancolombia', 'Ahorros', 'checking', 'COP', '****1234', ?)", (NOW,)
    )
    con.execute(
        "INSERT INTO cards (id, account_id, type, masked_number, alias, created_at)"
        " VALUES ('card-1', 'acc-co', 'debit', '****5678', 'Visa', ?)", (NOW,)
    )
    # (id, card, amount, merchant, date, type, channel, category)
    rows = [
        ("t1", "card-1", 35000, "El Corral", "2026-09-15T14:32:00Z", "debit", "sms", "food"),
        ("t2", None, 4500000, None, "2026-09-15T18:00:00Z", "transfer_in", "email", "transfers"),
        ("t3", None, 12500.5, "Café Nómina", "2026-09-30T23:30:00Z", "payment", "email", "services"),
        ("t4", None, 1000, "=HYPERLINK(\"x\")", "2026-09-20T10:00:00Z", "debit", "sms", "other"),
        ("t5", None, 200000, None, "2026-09-21T10:00:00Z", "transfer_out", "email", "transfers"),
        ("t8", None, 1000, "RAPPI;=1+1;", "2026-09-22T10:00:00Z", "debit", "sms", "other"),
        ("t9", None, 1000, "＝1+1", "2026-09-23T10:00:00Z", "debit", "sms", "other"),
        ("t6", None, 7000, "OCTOBER", "2026-10-01T00:00:00Z", "debit", "sms", "food"),
        ("t7", None, 9000, "AUGUST", "2026-08-31T23:59:59Z", "debit", "sms", "food"),
    ]
    for tid, card, amt, merch, date, ttype, channel, cat in rows:
        con.execute(
            "INSERT INTO transactions"
            " (id, account_id, card_id, amount, currency, merchant, date,"
            "  transaction_type, channel, category, message_hash, created_at, updated_at)"
            " VALUES (?, 'acc-co', ?, ?, 'COP', ?, ?, ?, ?, ?, ?, ?, ?)",
            (tid, card, amt, merch, date, ttype, channel, cat, f"hash-{tid}", NOW, NOW),
        )
    con.commit()
    con.close()


def run(*args: str, db_path: str, out_dir: str, verbose: bool = False) -> dict:
    env = {**os.environ, "HUSHMONEY_DB": db_path}
    if verbose:
        print(f"    $ export_csv.py {' '.join(args)}")
    proc = subprocess.run(
        [sys.executable, str(EXPORT), *args, "--out-dir", out_dir],
        capture_output=True, text=True, env=env,
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


def read_csv(path: str) -> tuple[str, list[list[str]]]:
    raw = Path(path).read_text(encoding="utf-8-sig")
    return raw, list(csv.reader(raw.splitlines()))


def main(verbose: bool = False) -> None:
    with _db.temp_db() as db_path, tempfile.TemporaryDirectory() as out_dir:
        _seed(db_path)
        print("\nexport export_csv eval\n")

        sept = run("--month", "2026-09", db_path=db_path, out_dir=out_dir, verbose=verbose)
        check("month_count", sept.get("count") == 7, str(sept))
        check("month_file_name", (sept.get("path") or "").endswith("hushmoney_2026-09.csv"), str(sept.get("path")))
        raw, rows = read_csv(sept["path"]) if sept.get("path") else ("", [[]])

        check("header_columns", rows[0] == COLUMNS, str(rows[0]))
        check("bom_for_excel", Path(sept.get("path", "")).read_bytes().startswith(b"\xef\xbb\xbf"))
        by_date = {r[0]: r for r in rows[1:]}
        check("sorted_oldest_first", [r[0] for r in rows[1:]] == sorted(by_date), str([r[0] for r in rows[1:]]))

        corral = by_date.get("2026-09-15T14:32:00Z", [])
        check("debit_is_negative", corral[1:4] == ["El Corral", "-35000", "COP"], str(corral))
        check("account_label", corral[6:8] == ["Bancolombia ****1234", "sms"], str(corral))
        payroll = by_date.get("2026-09-15T18:00:00Z", [])
        check("transfer_in_is_positive", payroll[1:3] == ["", "4500000"], str(payroll))
        cafe = by_date.get("2026-09-30T23:30:00Z", [])
        check("decimal_and_accents", cafe[1:3] == ["Café Nómina", "-12500.50"], str(cafe))
        transfer_out = by_date.get("2026-09-21T10:00:00Z", [])
        check("transfer_out_is_negative", transfer_out[2:3] == ["-200000"], str(transfer_out))
        formula = by_date.get("2026-09-20T10:00:00Z", [])
        check("formula_neutralised", formula[1:2] == ["'=HYPERLINK(\"x\")"], str(formula))
        fullwidth = by_date.get("2026-09-23T10:00:00Z", [])
        check("fullwidth_formula_neutralised", fullwidth[1:2] == ["'＝1+1"], str(fullwidth))
        # A ';' inside a value must stay inside quotes, or Excel with a ';' list
        # separator would start a new cell with "=1+1".
        check("separator_kept_inside_quotes", '"RAPPI;=1+1;"' in raw, raw)
        lines = raw.splitlines()
        check("every_cell_quoted", all(
            line.startswith('"') and line.endswith('"') and line.count('","') == len(COLUMNS) - 1
            for line in lines
        ), "\n".join(lines))

        check("no_ids_or_hashes", "hash-" not in raw and "acc-co" not in raw and "t1" not in raw)
        check("no_card_number", "5678" not in raw)

        rng = run("--from", "2026-09-30", "--to", "2026-10-01", db_path=db_path, out_dir=out_dir, verbose=verbose)
        check("range_inclusive_end_day", rng.get("count") == 2, str(rng))
        check("range_file_name", (rng.get("path") or "").endswith("hushmoney_2026-09-30_2026-10-01.csv"),
              str(rng.get("path")))
        check("previous_export_removed", not Path(sept.get("path", "/nonexistent")).exists())

        empty = run("--month", "2025-01", db_path=db_path, out_dir=out_dir, verbose=verbose)
        check("empty_period_no_file", empty.get("count") == 0 and empty.get("path") is None, str(empty))
        check("empty_run_clears_old_exports", not list(Path(out_dir).glob("*.csv")),
              str(list(Path(out_dir).glob("*.csv"))))

        print(f"\n  {_TOTAL - len(_FAILURES)}/{_TOTAL} passed")
        if _FAILURES:
            sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="store_true")
    main(verbose=parser.parse_args().verbose)
