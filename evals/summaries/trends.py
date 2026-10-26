#!/usr/bin/env python3
"""
summaries eval: spending trends vs. the previous period, and the rendered message.

No API key required — fully offline. Calls query_transactions.build_summary with a
fixed "now" against a seeded temp DB, so period boundaries are deterministic.

Covers what the user would notice if it silently regressed:
  - delta % and direction per category (up / down / flat / no_data)
  - "mayor variación" picks the biggest change in money, per currency
  - no previous data → no trend and no error
  - periods are local Bogotá days (a Sunday 22:30 purchase belongs to that week)
  - mid-period questions compare against the same span of the previous period
  - closed months compare against the full previous month
  - money in (transfer_in, credit) is income, never spending
  - daily and custom ranges carry no trends

Usage:
    python evals/summaries/trends.py
    python evals/summaries/trends.py -v
"""
from __future__ import annotations

import argparse
import importlib.util
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from lib import db as _db, models as _models

QUERY = _models.REPO_ROOT / "skills/summaries/scripts/query_transactions.py"
CREATED = "2026-01-01T00:00:00+00:00"

_spec = importlib.util.spec_from_file_location("query_transactions", QUERY)
qt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(qt)

_TOTAL = 0
_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global _TOTAL
    _TOTAL += 1
    print(f"  {'✓' if cond else '✗'} {name}" + ("" if cond else f"  — {detail}"))
    if not cond:
        _FAILURES.append(name)


def _seed(db_path: str, rows: list[tuple]) -> None:
    """rows: (id, account, amount, currency, utc_date, type, category)."""
    _db.seed_categories(db_path)
    con = sqlite3.connect(db_path)
    con.execute("INSERT INTO accounts (id, bank, type, currency, created_at)"
                " VALUES ('acc-co', 'bancolombia', 'checking', 'COP', ?)", (CREATED,))
    con.execute("INSERT INTO accounts (id, bank, type, currency, created_at)"
                " VALUES ('acc-us', 'davivienda', 'savings', 'USD', ?)", (CREATED,))
    for tid, acc, amount, currency, date, ttype, category in rows:
        con.execute(
            "INSERT INTO transactions (id, account_id, amount, currency, merchant, date,"
            " transaction_type, channel, category, message_hash, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, 'M', ?, ?, 'sms', ?, ?, ?, ?)",
            (tid, acc, amount, currency, date, ttype, category, f"h-{tid}", CREATED, CREATED),
        )
    con.commit()
    con.close()


def summarize(db_path: str, now_utc: str, *args: str, verbose: bool = False) -> dict:
    con = sqlite3.connect(db_path)
    try:
        out = qt.build_summary(con, qt.parse_args(list(args)), datetime.fromisoformat(now_utc))
    finally:
        con.close()
    if verbose:
        print(f"    $ {' '.join(args)} @ {now_utc}\n" + "\n".join(f"      {l}" for l in (out["text"] or "").splitlines()))
    return out


def _entry(out: dict, category: str | None, currency: str = "COP") -> dict:
    for e in out["spending_by_category"]:
        if e["category"] == category and e["currency"] == currency:
            return e
    return {}


# Closed week Mon 12 – Sun 18 Oct 2026 (Bogotá, UTC-5) vs. Mon 5 – Sun 11 Oct.
WEEK_ROWS = [
    ("c1", "acc-co", 100000, "COP", "2026-10-14T17:00:00Z", "debit", "food"),
    ("c2", "acc-co", 25000, "COP", "2026-10-19T03:30:00Z", "debit", "food"),        # Sun 18, 22:30 local
    ("c3", "acc-co", 45000, "COP", "2026-10-13T13:00:00Z", "debit", "transport"),
    ("c4", "acc-co", 80200, "COP", "2026-10-15T15:00:00Z", "debit", "shopping"),
    ("c5", "acc-co", 30000, "COP", "2026-10-16T15:00:00Z", "transfer_out", "health"),
    ("c6", "acc-us", 20, "USD", "2026-10-16T15:00:00Z", "debit", "food"),
    ("c7", "acc-co", 4500000, "COP", "2026-10-15T15:00:00Z", "transfer_in", "transfers"),
    ("c8", "acc-co", 100000, "COP", "2026-10-17T15:00:00Z", "credit", "food"),       # refund = money in
    ("c9", "acc-co", 999999, "COP", "2026-10-19T05:30:00Z", "debit", "food"),        # Mon 19, 00:30 local
    ("p1", "acc-co", 50000, "COP", "2026-10-07T17:00:00Z", "debit", "food"),
    ("p2", "acc-co", 50000, "COP", "2026-10-12T03:00:00Z", "debit", "food"),         # Sun 11, 22:00 local
    ("p3", "acc-co", 50000, "COP", "2026-10-08T15:00:00Z", "debit", "transport"),
    ("p4", "acc-co", 80000, "COP", "2026-10-09T15:00:00Z", "debit", "shopping"),
    ("p5", "acc-co", 20000, "COP", "2026-10-10T15:00:00Z", "debit", "entertainment"),
    ("p6", "acc-us", 10, "USD", "2026-10-09T15:00:00Z", "debit", "food"),
    ("p7", "acc-co", 7000, "COP", "2026-10-05T04:00:00Z", "debit", "food"),          # Sun 4, 23:00 local
]
MONDAY_9AM = "2026-10-19T14:00:00+00:00"


def eval_closed_week(verbose: bool) -> None:
    print("\n  closed week vs previous week")
    with _db.temp_db() as db_path:
        _seed(db_path, WEEK_ROWS)
        out = summarize(db_path, MONDAY_9AM, "--period", "week", "--offset", "-1", verbose=verbose)

    check("week_bounds_local", (out["from"], out["to"]) == ("2026-10-12T05:00:00Z", "2026-10-19T05:00:00Z"),
          f"{out['from']} → {out['to']}")
    check("week_spending_total", out["total_by_currency"] == {"COP": 280200.0, "USD": 20.0},
          str(out["total_by_currency"]))
    check("previous_total", out["previous"]["total_by_currency"] == {"COP": 250000.0, "USD": 10.0},
          str(out["previous"]["total_by_currency"]))
    check("income_separate", out["income_by_currency"] == {"COP": 4600000.0}, str(out["income_by_currency"]))

    expected = {
        "food": (25.0, "up"), "transport": (-10.0, "down"), "shopping": (0.2, "flat"),
        "health": (None, "no_data"), "entertainment": (-100.0, "down"),
    }
    for category, (pct, direction) in expected.items():
        trend = _entry(out, category).get("trend") or {}
        check(f"trend_{category}", (trend.get("delta_pct"), trend.get("direction")) == (pct, direction), str(trend))
    usd = _entry(out, "food", "USD").get("trend") or {}
    check("trend_usd_not_mixed", (usd.get("delta_pct"), usd.get("previous_total")) == (100.0, 10), str(usd))

    changes = out["biggest_change"]
    check("biggest_change_cop", (changes.get("COP", {}).get("category"), changes.get("COP", {}).get("delta_amount"))
          == ("food", 25000.0), str(changes.get("COP")))
    check("biggest_change_usd", changes.get("USD", {}).get("delta_amount") == 10.0, str(changes.get("USD")))

    text = out["text"] or ""
    for fragment in (
        "📊 Resumen semanal — 12–18 oct",
        "💸 Total gastado: $280,200 · USD 20",
        "🍔 Comida: $125,000  ↑ 25% vs sem. anterior",
        "🚌 Transporte: $45,000  ↓ 10% vs sem. anterior",
        "🛍️ Compras: $80,200  → igual",
        "📥 Recibido: $4,600,000",
        "⚠️ Mayor variación: Comida subió $25,000",
        "⚠️ Mayor variación: Comida subió USD 10",
    ):
        check(f"text_has: {fragment}", fragment in text, text)
    check("text_new_category_without_trend", "💊 Salud: $30,000\n" in text, text)
    check("text_skips_categories_with_no_spending", "Entretenimiento" not in text, text)


def eval_no_previous_data(verbose: bool) -> None:
    print("\n  no data in the previous period")
    with _db.temp_db() as db_path:
        _seed(db_path, [r for r in WEEK_ROWS if r[0].startswith("c")])
        out = summarize(db_path, MONDAY_9AM, "--period", "week", "--offset", "-1", verbose=verbose)
    directions = {e["trend"]["direction"] for e in out["spending_by_category"]}
    check("all_no_data", directions == {"no_data"}, str(directions))
    check("no_biggest_change", out["biggest_change"] == {}, str(out["biggest_change"]))
    text = out["text"] or ""
    check("text_without_trends", "vs sem." not in text and "Mayor variación" not in text, text)


def eval_mid_week(verbose: bool) -> None:
    print("\n  mid-week question compares the same span")
    rows = [
        ("m1", "acc-co", 20000, "COP", "2026-10-13T15:00:00Z", "debit", "food"),
        ("m2", "acc-co", 10000, "COP", "2026-10-06T15:00:00Z", "debit", "food"),
        ("m3", "acc-co", 50000, "COP", "2026-10-09T15:00:00Z", "debit", "food"),  # after Wed noon last week
    ]
    with _db.temp_db() as db_path:
        _seed(db_path, rows)
        out = summarize(db_path, "2026-10-14T17:00:00+00:00", "--period", "week", verbose=verbose)
    check("same_span_previous_to", out["previous"]["to"] == "2026-10-07T17:00:00Z", out["previous"]["to"])
    check("same_span_previous_total", out["previous"]["total_by_currency"] == {"COP": 10000.0},
          str(out["previous"]["total_by_currency"]))
    check("same_span_trend", (_entry(out, "food").get("trend") or {}).get("delta_pct") == 100.0,
          str(_entry(out, "food")))
    check("partial_week_header", "Resumen semanal — 12–14 oct" in (out["text"] or ""), out["text"] or "")


def eval_months(verbose: bool) -> None:
    print("\n  months")
    rows = [
        ("j1", "acc-co", 30000, "COP", "2026-02-01T01:00:00Z", "debit", "food"),  # Jan 31, 20:00 local
        ("f1", "acc-co", 60000, "COP", "2026-02-10T15:00:00Z", "debit", "food"),
    ]
    with _db.temp_db() as db_path:
        _seed(db_path, rows)
        closed = summarize(db_path, "2026-03-01T14:00:00+00:00", "--period", "month", "--offset", "-1", verbose=verbose)
        partial = summarize(db_path, "2026-03-31T17:00:00+00:00", "--period", "month")
        year = summarize(db_path, "2026-02-01T14:00:00+00:00", "--period", "month", "--offset", "-1")

    check("closed_month_vs_full_previous", closed["previous"] == {
        "from": "2026-01-01T05:00:00Z", "to": "2026-02-01T05:00:00Z", "total_by_currency": {"COP": 30000.0},
    }, str(closed["previous"]))
    check("closed_month_trend", (_entry(closed, "food").get("trend") or {}).get("delta_pct") == 100.0,
          str(_entry(closed, "food")))
    text = closed["text"] or ""
    check("month_header_and_label", "Resumen mensual — febrero 2026" in text and "↑ 100% vs mes anterior" in text, text)
    check("partial_month_clamped_to_previous_end", partial["previous"]["to"] == "2026-03-01T05:00:00Z",
          partial["previous"]["to"])
    check("month_across_year", (year["from"], year["previous"]["from"]) == ("2026-01-01T05:00:00Z", "2025-12-01T05:00:00Z"),
          f"{year['from']} / {year['previous']['from']}")


def eval_without_trends() -> None:
    print("\n  daily and custom ranges carry no trends")
    with _db.temp_db() as db_path:
        _seed(db_path, WEEK_ROWS)
        daily = summarize(db_path, "2026-10-14T23:00:00+00:00", "--period", "today")
        custom = summarize(db_path, MONDAY_9AM, "--from", "2026-10-18", "--to", "2026-10-18")
        empty = summarize(db_path, "2026-11-30T14:00:00+00:00", "--period", "week", "--offset", "-1")
    check("daily_no_trends", daily["previous"] is None and daily["text"] is None
          and all(e["trend"] is None for e in daily["spending_by_category"]), str(daily["previous"]))
    check("daily_local_day", daily["count"] == 1, str(daily["count"]))
    check("custom_no_trends", custom["previous"] is None and custom["text"] is None, str(custom["previous"]))
    check("custom_to_date_includes_whole_local_day", [t["id"] for t in custom["transactions"]] == ["c2"],
          str([t["id"] for t in custom["transactions"]]))
    check("empty_week_still_renders", "Sin gastos registrados" in (empty["text"] or ""), empty["text"] or "")


def main(verbose: bool = False) -> None:
    print("\nsummaries trends eval")
    eval_closed_week(verbose)
    eval_no_previous_data(verbose)
    eval_mid_week(verbose)
    eval_months(verbose)
    eval_without_trends()
    print(f"\n  {_TOTAL - len(_FAILURES)}/{_TOTAL} passed")
    if _FAILURES:
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="store_true")
    main(verbose=parser.parse_args().verbose)
