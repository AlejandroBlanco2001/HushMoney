#!/usr/bin/env python3
"""
Categorizer eval: LLM category + needs_clarification detection.

Tests two things against a fixed fixture set:
  1. Does the model return the correct category slug for unambiguous merchants?
  2. Does the model correctly flag ambiguous merchants as needs_clarification?

Ground truth is baked into the fixtures below — no manual labeling needed.

Usage:
    export NEBIUS_API_KEY=sk-...   (or set in .env at repo root)
    python evals/categorizer/run.py
    python evals/categorizer/run.py --model super   # run a single model tier
    python evals/categorizer/run.py --score         # re-score existing results.json
    python evals/categorizer/run.py --dry-run       # verify fixtures, no API calls
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
MODELS = _models.MODELS

CATEGORIES = [
    "food", "transport", "entertainment", "health",
    "shopping", "services", "transfers", "cash", "other",
]


# ── Fixtures ───────────────────────────────────────────────────────────────────
# Each fixture has:
#   merchant        — normalized bank-emitted string
#   payload         — clean transaction payload
#   expected        — correct category slug, or "needs_clarification"
#   label           — human-readable description for the report

@dataclass
class Fixture:
    name: str
    merchant: str
    payload: dict[str, Any]
    expected: str  # slug or "needs_clarification"


FIXTURES: list[Fixture] = [
    # ── Unambiguous: should be categorized directly ───────────────────────────
    Fixture(
        name="netflix_subscription",
        merchant="NETFLIX",
        payload={"amount": 17900, "currency": "COP", "merchant": "NETFLIX",
                 "transaction_type": "debit", "account_type": "credit", "channel": "email"},
        expected="entertainment",
    ),
    Fixture(
        name="uber_rides",
        merchant="UBER RIDES",
        payload={"amount": 32500, "currency": "COP", "merchant": "UBER RIDES",
                 "transaction_type": "debit", "account_type": "checking", "channel": "sms"},
        expected="transport",
    ),
    Fixture(
        name="mcd_fast_food",
        merchant="MCD",
        payload={"amount": 28000, "currency": "COP", "merchant": "MCD",
                 "transaction_type": "debit", "account_type": "checking", "channel": "sms"},
        expected="food",
    ),
    Fixture(
        name="spotify_subscription",
        merchant="SPOTIFY",
        payload={"amount": 14900, "currency": "COP", "merchant": "SPOTIFY",
                 "transaction_type": "debit", "account_type": "credit", "channel": "email"},
        expected="entertainment",
    ),
    Fixture(
        name="smartfit_gym",
        merchant="SMARTFIT",
        payload={"amount": 89900, "currency": "COP", "merchant": "SMARTFIT",
                 "transaction_type": "debit", "account_type": "checking", "channel": "email"},
        expected="health",
    ),
    Fixture(
        name="atm_cash_withdrawal",
        merchant="CAJERO BANCOLOMBIA",
        payload={"amount": 200000, "currency": "COP", "merchant": "CAJERO BANCOLOMBIA",
                 "transaction_type": "cash", "account_type": "checking", "channel": "sms"},
        expected="cash",
    ),
    Fixture(
        name="transfer_out",
        merchant=None,
        payload={"amount": 150000, "currency": "COP", "merchant": None,
                 "transaction_type": "transfer_out", "account_type": "checking", "channel": "sms"},
        expected="transfers",
    ),
    Fixture(
        name="claro_telecom",
        merchant="CLARO",
        payload={"amount": 55000, "currency": "COP", "merchant": "CLARO",
                 "transaction_type": "debit", "account_type": "checking", "channel": "sms"},
        expected="services",
    ),
    Fixture(
        name="exito_supermarket",
        merchant="EXITO",
        payload={"amount": 87600, "currency": "COP", "merchant": "EXITO",
                 "transaction_type": "debit", "account_type": "checking", "channel": "sms"},
        expected="food",
    ),
    Fixture(
        name="alkosto_electronics",
        merchant="ALKOSTO",
        payload={"amount": 1250000, "currency": "COP", "merchant": "ALKOSTO",
                 "transaction_type": "debit", "account_type": "credit", "channel": "email"},
        expected="shopping",
    ),
    # ── Ambiguous: should trigger needs_clarification ─────────────────────────
    Fixture(
        name="rappi_ambiguous",
        merchant="RAPPI",
        payload={"amount": 47350, "currency": "COP", "merchant": "RAPPI",
                 "transaction_type": "debit", "account_type": "checking", "channel": "sms"},
        expected="needs_clarification",
    ),
    Fixture(
        name="pexto_capital_gateway",
        merchant="PEXTO CAPITAL SAS",
        payload={"amount": 120000, "currency": "COP", "merchant": "PEXTO CAPITAL SAS",
                 "transaction_type": "payment", "account_type": "checking", "channel": "sms"},
        expected="needs_clarification",
    ),
    Fixture(
        name="amazon_ambiguous",
        merchant="AMAZON",
        payload={"amount": 35000, "currency": "COP", "merchant": "AMAZON",
                 "transaction_type": "debit", "account_type": "credit", "channel": "email"},
        expected="needs_clarification",
    ),
    Fixture(
        name="payu_gateway",
        merchant="PAYU COLOMBIA",
        payload={"amount": 89000, "currency": "COP", "merchant": "PAYU COLOMBIA",
                 "transaction_type": "payment", "account_type": "credit", "channel": "email"},
        expected="needs_clarification",
    ),
]


# ── Prompt ─────────────────────────────────────────────────────────────────────

def _make_prompt() -> str:
    cats = ", ".join(CATEGORIES)
    return f"""You are a transaction categorizer for a personal finance app.

Given a clean transaction payload as JSON, respond with ONLY a JSON object.

Confident case:
{{"category": "<one of the valid categories>"}}

Uncertain case — merchant is a payment gateway or multi-service platform where the
actual purchase purpose cannot be determined from the name alone (e.g. PayU, Stripe,
Adyen, Rappi, Amazon, or any generic capital/financial services company):
{{"category": "needs_clarification", "reason": "payment_gateway"}}

Valid categories: {cats}

Rules:
- transaction_type "transfer_out" or "transfer_in" → always "transfers"
- transaction_type "cash" → always "cash"
- Ride-hailing apps → "transport"
- Streaming, gaming → "entertainment"
- Pharmacies, clinics, gyms → "health"
- Utility and telecom providers → "services"
- No merchant field → infer from transaction_type

Respond with only the JSON object, no explanation."""


# ── API helpers ────────────────────────────────────────────────────────────────


def call_model(api_key: str, model_id: str, fixture: Fixture) -> dict[str, Any]:
    resp = api.chat_completion(
        api_key, model_id,
        messages=[
            {"role": "system", "content": _make_prompt()},
            {"role": "user", "content": json.dumps(fixture.payload)},
        ],
        max_tokens=64,
    )
    result = api.extract_json(resp["content"], valid_values=CATEGORIES + ["needs_clarification"])
    cat = str(result.get("category") or result.get("_scanned") or "other").lower().strip()
    return {
        "category": cat,
        "reason": str(result.get("reason", "")),
        "correct": cat == fixture.expected,
        "latency_ms": resp["latency_ms"],
        "input_tokens": resp["input_tokens"],
        "output_tokens": resp["output_tokens"],
        "error": None,
    }


# ── Run ────────────────────────────────────────────────────────────────────────

def run(model_filter: str | None = None, dry_run: bool = False) -> None:
    if dry_run:
        print(f"[dry-run] {len(FIXTURES)} fixtures\n")
        for f in FIXTURES:
            print(f"  {f.name:<40} expected={f.expected}")
        return

    api.load_dotenv()
    api_key = os.environ.get("NEBIUS_API_KEY", "")
    if not api_key:
        print("ERROR: NEBIUS_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    models = [m for m in MODELS if model_filter is None or m["key"] == model_filter]
    if not models:
        print(f"ERROR: unknown model '{model_filter}' — choose: nano, super, ultra", file=sys.stderr)
        sys.exit(1)

    cases = [
        {
            "fixture": f.name,
            "merchant": f.merchant,
            "expected": f.expected,
            "models": {},
        }
        for f in FIXTURES
    ]

    for model in models:
        print(f"\n{model['label']}")
        print("-" * 50)
        for i, fixture in enumerate(FIXTURES):
            try:
                result = call_model(api_key, model["id"], fixture)
                cases[i]["models"][model["key"]] = result
                mark = "✓" if result["correct"] else "✗"
                label = result["category"]
                if result.get("reason"):
                    label += f" ({result['reason']})"
                print(f"  {mark} {fixture.name:<38} {label:<28} {result['latency_ms']:>5}ms")
            except Exception as e:
                cases[i]["models"][model["key"]] = {
                    "category": None, "reason": "", "correct": False,
                    "latency_ms": None, "input_tokens": 0, "output_tokens": 0,
                    "error": str(e),
                }
                print(f"  ✗ {fixture.name:<38} ERROR: {e}")
            time.sleep(0.2)

    with RESULTS_FILE.open("w") as f:
        json.dump(cases, f, indent=2, ensure_ascii=False)

    print(f"\nResults written to {RESULTS_FILE.relative_to(REPO_ROOT)}")
    score(cases)


# ── Score ──────────────────────────────────────────────────────────────────────

def score(cases: list[dict] | None = None) -> None:
    if cases is None:
        if not RESULTS_FILE.exists():
            print("No results.json — run the experiment first.", file=sys.stderr)
            sys.exit(1)
        with RESULTS_FILE.open() as f:
            cases = json.load(f)

    total = len(cases)
    unambiguous = [c for c in cases if c["expected"] != "needs_clarification"]
    ambiguous = [c for c in cases if c["expected"] == "needs_clarification"]

    run_models = {k for c in cases for k in c["models"]}
    models = [m for m in MODELS if m["key"] in run_models]

    print(f"\n{'=' * 72}")
    print(f"CATEGORIZER EVAL  ({total} fixtures: {len(unambiguous)} unambiguous, {len(ambiguous)} ambiguous)")
    print(f"{'=' * 72}\n")

    print(f"  {'Model':<28} {'Overall':>7}  {'Unambiguous':>11}  {'Clarification':>13}  {'$/1K':>8}")
    print(f"  {'-' * 70}")

    for model in models:
        key = model["key"]
        model_cases = [c for c in cases if key in c["models"] and not c["models"][key].get("error")]
        if not model_cases:
            print(f"  {model['label']:<28}  no data")
            continue

        def acc(subset):
            if not subset:
                return float("nan")
            hits = [c for c in subset if key in c["models"] and c["models"][key].get("correct")]
            eligible = [c for c in subset if key in c["models"] and not c["models"][key].get("error")]
            return len(hits) / len(eligible) if eligible else float("nan")

        avg_in  = sum(c["models"][key]["input_tokens"]  for c in model_cases) / len(model_cases)
        avg_out = sum(c["models"][key]["output_tokens"] for c in model_cases) / len(model_cases)
        cost = (avg_in / 1_000_000) * model["input_per_m"] + (avg_out / 1_000_000) * model["output_per_m"]

        print(
            f"  {model['label']:<28} {acc(model_cases):>7.1%}  "
            f"{acc(unambiguous):>11.1%}  {acc(ambiguous):>13.1%}  ${cost * 1000:>7.4f}"
        )

    print(f"\n  {'Fixture':<40} {'Expected':<22}", end="")
    for m in models:
        print(f"  {m['key']:>6}", end="")
    print()
    print(f"  {'-' * (66 + len(models) * 9)}")

    for case in cases:
        print(f"  {case['fixture']:<40} {case['expected']:<22}", end="")
        for m in models:
            key = m["key"]
            if key not in case["models"]:
                print(f"  {'—':>6}", end="")
                continue
            r = case["models"][key]
            if r.get("error"):
                print(f"  {'err':>6}", end="")
            else:
                mark = "✓" if r["correct"] else "✗"
                print(f"  {mark + r['category'][:5]:>6}", end="")
        print()

    print()


# ── Entry ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=None, help="nano | super | ultra")
    parser.add_argument("--score", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.score:
        score()
    elif args.dry_run:
        run(dry_run=True)
    else:
        run(model_filter=args.model)
