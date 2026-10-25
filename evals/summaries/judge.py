#!/usr/bin/env python3
"""
summaries LLM-as-judge eval.

Summary *text* quality is subjective, so a second model call scores it. For each
fixture transaction set we:
  1. generate a summary from the query_transactions-shaped JSON, using the same
     formatting rules the summaries skill follows (skills/summaries/SKILL.md);
  2. judge that summary with a rubric call that checks the things that actually
     hurt the user — wrong totals, mixed currencies, invented transactions,
     dropped transfer_out, or an inappropriate tone.

Needs NEBIUS_API_KEY (the deterministic surface is covered by query.py). When no
key is set the eval skips with exit 0, so keyless/CI-default contexts are not
broken; the manual evals workflow supplies the key and runs it for real.

Usage:
    export NEBIUS_API_KEY=sk-...            # or set in .env at repo root
    python evals/summaries/judge.py
    python evals/summaries/judge.py --model super     # nano | super | ultra
    python evals/summaries/judge.py --dry-run         # list fixtures, no API calls
    python evals/summaries/judge.py --score           # re-score existing results.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))
from lib import api, models as _models

REPO_ROOT = _models.REPO_ROOT
RESULTS_FILE = Path(__file__).parent / "results.json"
MODELS_BY_KEY = _models.MODELS_BY_KEY

THRESHOLD = 0.80   # fraction of fixtures that must pass
OVERALL_MIN = 4    # minimum judge "overall" (1–5) for a fixture to pass


# ── Fixtures ─────────────────────────────────────────────────────────────────
# Each `data` is exactly what query_transactions.py emits. The judge verifies the
# generated summary against this ground truth, so no answer is leaked to generation.

@dataclass
class Fixture:
    name: str
    period: str
    data: dict[str, Any]
    note: str  # what this fixture stresses (for humans / dry-run)


def _tx(id, amount, currency, merchant, ttype, category, acct, card=None):
    return {
        "id": id, "amount": amount, "currency": currency, "merchant": merchant,
        "date": "2026-10-15T12:00:00Z", "transaction_type": ttype, "channel": "sms",
        "category": category, "description": None, "account": acct, "card": card,
    }


_ACCT_DEBITO = {"bank": "bancolombia", "alias": "Bancolombia débito", "type": "checking", "masked_number": "****1234"}
_ACCT_VISA = {"bank": "bancolombia", "alias": "Visa Bancolombia", "type": "credit", "masked_number": None}
_CARD_VISA = {"alias": "Visa Bancolombia", "masked_number": "****9012", "type": "credit"}
_ACCT_USD = {"bank": "davivienda", "alias": None, "type": "savings", "masked_number": None}


FIXTURES: list[Fixture] = [
    Fixture(
        name="week_two_accounts",
        period="this week",
        data={
            "transactions": [
                _tx("t1", 6930, "COP", "UBER", "debit", "transport", _ACCT_DEBITO),
                _tx("t2", 32000, "COP", "RAPPI", "debit", "food", _ACCT_DEBITO),
                _tx("t3", 18900, "COP", "NETFLIX", "debit", "entertainment", _ACCT_VISA, _CARD_VISA),
            ],
            "total_by_currency": {"COP": 57830.0},
            "count": 3,
        },
        note="grouping by account, card shown, single-currency total 57,830",
    ),
    Fixture(
        name="multi_currency",
        period="this month",
        data={
            "transactions": [
                _tx("t1", 45000, "COP", "EXITO", "debit", "food", _ACCT_DEBITO),
                _tx("t2", 20, "USD", "STEAM", "debit", "entertainment", _ACCT_USD),
            ],
            "total_by_currency": {"COP": 45000.0, "USD": 20.0},
            "count": 2,
        },
        note="two currencies must be totalled separately, never mixed",
    ),
    Fixture(
        name="transfer_out_counts",
        period="this week",
        data={
            "transactions": [
                _tx("t1", 6930, "COP", "UBER", "debit", "transport", _ACCT_DEBITO),
                _tx("t2", 100000, "COP", None, "transfer_out", "transfers", _ACCT_DEBITO),
            ],
            "total_by_currency": {"COP": 106930.0},
            "count": 2,
        },
        note="transfer_out is outgoing money and must be counted in the total",
    ),
    Fixture(
        name="empty_period",
        period="today",
        data={"transactions": [], "total_by_currency": {}, "count": 0},
        note="no transactions → must say so, must not invent any",
    ),
]


# ── Prompts ──────────────────────────────────────────────────────────────────

def _generation_prompt() -> str:
    return """You generate a spending summary for a personal finance assistant.

You receive JSON from query_transactions (transactions + total_by_currency + count).
Produce ONLY the summary message a user would receive. Rules:
- If count == 0: reply exactly "No spending recorded for this period." and nothing else.
- Group transactions by account alias (fallback: bank + type if no alias).
- Show the card masked_number when a transaction's "card" is not null.
- Show the category in parentheses when set; omit it when null.
- Give a total per currency. NEVER add different currencies into one total.
- transfer_out counts as spending (money left the account); include it in totals.
- Only report transactions present in the JSON — never invent any.
- Keep the tone neutral and factual: not alarming, not preachy.

Respond with only the summary text."""


def _judge_prompt() -> str:
    return """You are a strict evaluator of spending-summary messages.

You are given the ground-truth transaction JSON and a SUMMARY generated from it.
Check the summary against the JSON and respond with ONLY a JSON object:

{"totals_correct": true|false,   // every per-currency total equals the sum of its transactions, currencies not mixed; for count==0 this is trivially true
 "no_fabrication": true|false,   // the summary mentions no transaction/merchant/amount absent from the JSON
 "faithful": 1-5,                // how completely and correctly it reflects the transactions (grouping, categories, cards)
 "tone": 1-5,                    // 5 = neutral/factual, 1 = alarming or preachy
 "overall": 1-5,                 // holistic quality
 "reason": "<one short sentence>"}

Be unforgiving about totals and fabrication. Respond with only the JSON object."""


# ── Model calls ──────────────────────────────────────────────────────────────

def generate_summary(api_key: str, model_id: str, fixture: Fixture) -> dict[str, Any]:
    resp = api.chat_completion(
        api_key, model_id,
        messages=[
            {"role": "system", "content": _generation_prompt()},
            {"role": "user", "content": json.dumps(fixture.data, ensure_ascii=False)},
        ],
        # Nemotron tiers emit reasoning into a separate field before the answer;
        # the budget must cover that reasoning plus the summary, or `content` comes
        # back empty and the API helper falls back to the truncated monologue.
        max_tokens=2048,
    )
    return resp


def judge_summary(api_key: str, model_id: str, fixture: Fixture, summary: str) -> dict[str, Any]:
    user = (
        f"GROUND TRUTH JSON:\n{json.dumps(fixture.data, ensure_ascii=False)}\n\n"
        f"SUMMARY:\n{summary}"
    )
    resp = api.chat_completion(
        api_key, model_id,
        messages=[
            {"role": "system", "content": _judge_prompt()},
            {"role": "user", "content": user},
        ],
        max_tokens=1536,  # reasoning budget + the JSON verdict
    )
    verdict = api.extract_json(resp["content"])
    return {
        "totals_correct": bool(verdict.get("totals_correct")),
        "no_fabrication": bool(verdict.get("no_fabrication")),
        "faithful": _as_int(verdict.get("faithful")),
        "tone": _as_int(verdict.get("tone")),
        "overall": _as_int(verdict.get("overall")),
        "reason": str(verdict.get("reason", "")),
    }


def _as_int(value: Any) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0


def _passed(verdict: dict[str, Any]) -> bool:
    return bool(
        verdict.get("totals_correct")
        and verdict.get("no_fabrication")
        and verdict.get("overall", 0) >= OVERALL_MIN
    )


# ── Run ──────────────────────────────────────────────────────────────────────

def run(model_key: str, dry_run: bool = False) -> None:
    if dry_run:
        print(f"[dry-run] {len(FIXTURES)} fixtures\n")
        for f in FIXTURES:
            print(f"  {f.name:<24} period={f.period:<11} — {f.note}")
        return

    api.load_dotenv()
    api_key = os.environ.get("NEBIUS_API_KEY", "")
    if not api_key:
        print("NEBIUS_API_KEY not set — skipping summaries judge eval (needs a key).")
        return

    model = MODELS_BY_KEY.get(model_key)
    if model is None:
        print(f"ERROR: unknown model '{model_key}' — choose nano, super, ultra", file=sys.stderr)
        sys.exit(1)

    print(f"\nSummaries judge eval — {model['label']}\n")
    cases: list[dict[str, Any]] = []

    for fixture in FIXTURES:
        try:
            gen = generate_summary(api_key, model["id"], fixture)
            summary = gen["content"]
            verdict = judge_summary(api_key, model["id"], fixture, summary)
            mark = "✓" if _passed(verdict) else "✗"
            print(
                f"  {mark} {fixture.name:<24} totals={verdict['totals_correct']!s:<5} "
                f"fab_ok={verdict['no_fabrication']!s:<5} overall={verdict['overall']}  "
                f"{verdict['reason']}"
            )
            cases.append({
                "fixture": fixture.name,
                "summary": summary,
                "verdict": verdict,
                "passed": _passed(verdict),
            })
        except Exception as exc:  # any API/parse failure is a case failure
            print(f"  ✗ {fixture.name:<24} ERROR: {exc}")
            cases.append({"fixture": fixture.name, "summary": None, "verdict": None,
                          "passed": False, "error": str(exc)})
        time.sleep(0.2)

    with RESULTS_FILE.open("w") as f:
        json.dump(cases, f, indent=2, ensure_ascii=False)
    print(f"\nResults written to {RESULTS_FILE.relative_to(REPO_ROOT)}")

    score(cases)


def score(cases: list[dict[str, Any]] | None = None) -> None:
    if cases is None:
        if not RESULTS_FILE.exists():
            print("No results.json — run the eval first.", file=sys.stderr)
            sys.exit(1)
        with RESULTS_FILE.open() as f:
            cases = json.load(f)

    total = len(cases)
    passed = sum(1 for c in cases if c.get("passed"))
    rate = passed / total if total else 0.0

    print(f"\n  {passed}/{total} fixtures passed  ({rate:.0%}, threshold {THRESHOLD:.0%})")

    # Totals and fabrication are hard failures regardless of the pass rate.
    hard = [
        c["fixture"] for c in cases
        if c.get("verdict") and (
            not c["verdict"].get("totals_correct") or not c["verdict"].get("no_fabrication")
        )
    ]
    if hard:
        print(f"\nFAILED: wrong totals or fabrication in: {', '.join(hard)}", file=sys.stderr)
        sys.exit(1)
    if rate < THRESHOLD:
        print(f"\nFAILED: pass rate {rate:.0%} below {THRESHOLD:.0%} threshold", file=sys.stderr)
        sys.exit(1)


# ── Entry ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="super", help="nano | super | ultra")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--score", action="store_true")
    args = parser.parse_args()

    if args.score:
        score()
    else:
        run(args.model, dry_run=args.dry_run)
