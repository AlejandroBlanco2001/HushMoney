#!/usr/bin/env python3
"""
Model selection experiment for Hermes categorizer.

Sends each fixture's clean payload to three NVIDIA Nemotron tiers on Nebius,
records the predicted category, latency, and token usage, then writes results.json.

You manually fill in `correct_category` in results.json, then run --score to get
the full accuracy / latency / cost comparison.

The labeled results.json doubles as the seed for skills/categorizer/evals/golden.jsonl.

Usage:
    # Add NEBIUS_API_KEY to .env at the repo root (copy from .env.example)
    python evals/model_selection/run.py              # run experiment → results.json
    python evals/model_selection/run.py --score      # score labeled results.json
    python evals/model_selection/run.py --dry-run    # verify fixture discovery, no API calls
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
from pathlib import Path
from typing import Any


sys.path.insert(0, str(Path(__file__).parent.parent))
from lib import api
from lib import models as _models


REPO_ROOT = _models.REPO_ROOT
RESULTS_FILE = Path(__file__).parent / 'results.json'
MODELS = _models.MODELS

# Default category set shipped with the app — user can add/remove via Telegram.
# In production the categorizer skill reads this list from SQLite at call time.
STARTER_CATEGORIES = [
    'dining',
    'groceries',
    'food_delivery',
    'transport',
    'fuel',
    'shopping',
    'entertainment',
    'subscriptions',
    'utilities',
    'health',
    'fitness',
    'travel',
    'accommodation',
    'transfer',
    'cash',
    'services',
    'other',
]


def make_system_prompt(categories: list[str]) -> str:
    cats = ', '.join(categories)
    return f"""You are a transaction categorizer for a personal finance app.

Given a clean transaction payload as JSON, respond with ONLY a JSON object.

Confident case:
{{"category": "<one of the valid categories>"}}

Uncertain case — merchant is a payment gateway or processor where the actual
purchase purpose cannot be determined from the name alone (e.g. PayU, Stripe,
Adyen, or any generic capital/financial services company):
{{"category": "needs_clarification", "reason": "payment_gateway"}}

Valid categories: {cats}

Rules:
- transaction_type "transfer_out" or "transfer_in" → always "transfer"
- transaction_type "cash" → always "cash"
- Ride-hailing apps → "transport"
- Food delivery platforms → "food_delivery"
- Streaming, gaming, cinema → "entertainment" or "subscriptions"
- Pharmacies, clinics → "health"
- Utility and telecom providers → "utilities"
- No merchant field → infer from transaction_type

Respond with only the JSON object, no explanation."""


# ── Fixtures ───────────────────────────────────────────────────────────────────


def discover_fixtures() -> list[dict[str, Any]]:
    root = REPO_ROOT / 'tests' / 'fixtures'
    cases: list[dict[str, Any]] = []

    for path in sorted(root.rglob('*.expected.json')):
        rel = path.relative_to(root)
        key = str(rel).replace('.expected.json', '')
        with path.open() as f:
            payload = json.load(f)
        cases.append(
            {
                'fixture': key,
                'input': payload,
                'correct_category': None,  # fill in manually after running
                'models': {},
            }
        )

    return cases


# ── API ────────────────────────────────────────────────────────────────────────


def call_model(
    api_key: str,
    model_id: str,
    payload: dict[str, Any],
    categories: list[str] = STARTER_CATEGORIES,
) -> dict[str, Any]:
    resp = api.chat_completion(
        api_key,
        model_id,
        messages=[
            {'role': 'system', 'content': make_system_prompt(categories)},
            {'role': 'user', 'content': json.dumps(payload)},
        ],
        max_tokens=256,
    )
    result = api.extract_json(resp['content'], valid_values=[*categories, 'needs_clarification'])
    return {
        'category': str(result.get('category') or result.get('_scanned') or 'unknown')
        .lower()
        .strip(),
        'reason': str(result.get('reason', '')),
        'latency_ms': resp['latency_ms'],
        'input_tokens': resp['input_tokens'],
        'output_tokens': resp['output_tokens'],
        'error': None,
    }


# ── Run ────────────────────────────────────────────────────────────────────────


def run_experiment(dry_run: bool = False) -> None:
    if dry_run:
        print('[dry-run: fixture discovery only, no API calls]\n')
    else:
        api.load_dotenv()
        api_key = os.environ.get('NEBIUS_API_KEY', '')
        if not api_key:
            print('ERROR: NEBIUS_API_KEY not set', file=sys.stderr)
            sys.exit(1)

    cases = discover_fixtures()
    print(f'Found {len(cases)} fixtures\n')

    for case in cases:
        print(f'  {case["fixture"]}')

        if dry_run:
            for model in MODELS:
                print(f'    [{model["key"]:5}] (skipped)')
            print()
            continue

        for model in MODELS:
            try:
                result = call_model(api_key, model['id'], case['input'])  # type: ignore[possibly-undefined]
                case['models'][model['key']] = result
                label = result['category']
                if result.get('reason'):
                    label = f'{label} ({result["reason"]})'
                print(
                    f'    [{model["key"]:5}] {label:<30} '
                    f'{result["latency_ms"]:>5}ms  '
                    f'{result["input_tokens"]}+{result["output_tokens"]} tok'
                )
            except urllib.error.HTTPError as e:
                err = f'HTTP {e.code}: {e.reason}'
                case['models'][model['key']] = {
                    'category': None,
                    'reason': '',
                    'latency_ms': None,
                    'input_tokens': 0,
                    'output_tokens': 0,
                    'error': err,
                }
                print(f'    [{model["key"]:5}] ERROR: {err}')
            except Exception as e:
                case['models'][model['key']] = {
                    'category': None,
                    'reason': '',
                    'latency_ms': None,
                    'input_tokens': 0,
                    'output_tokens': 0,
                    'error': str(e),
                }
                print(f'    [{model["key"]:5}] ERROR: {e}')

            time.sleep(0.25)

        print()

    if not dry_run:
        with RESULTS_FILE.open('w') as f:
            json.dump(cases, f, indent=2, ensure_ascii=False)

        print(f'Written to {RESULTS_FILE.relative_to(REPO_ROOT)}')
        print()
        print('Next steps:')
        print('  1. Open results.json')
        print('  2. Fill in "correct_category" for each fixture')
        print('  3. Run:  python evals/model_selection/run.py --score')
        print()
        print('Tip: the labeled file is the seed for skills/categorizer/evals/golden.jsonl')


# ── Score ──────────────────────────────────────────────────────────────────────


def score() -> None:
    if not RESULTS_FILE.exists():
        print('No results.json found — run the experiment first.', file=sys.stderr)
        sys.exit(1)

    with RESULTS_FILE.open() as f:
        cases: list[dict[str, Any]] = json.load(f)

    labeled = [c for c in cases if c.get('correct_category')]
    if not labeled:
        print("No labeled cases yet — fill in 'correct_category' in results.json first.")
        sys.exit(0)

    print(f'\n{"=" * 76}')
    print(f'HERMES MODEL SELECTION  ({len(labeled)} labeled / {len(cases)} total fixtures)')
    print(f'{"=" * 76}\n')
    print(
        f'  {"Model":<28} {"Acc":>5}  {"Avg latency":>11}  '
        f'{"Tokens in/out":>14}  {"$/1K calls":>10}'
    )
    print(f'  {"-" * 74}')

    for model in MODELS:
        key = model['key']
        model_cases = [
            c for c in labeled if key in c['models'] and not c['models'][key].get('error')
        ]

        if not model_cases:
            print(f'  {model["label"]:<28}  no data')
            continue

        correct = sum(
            1 for c in model_cases if c['models'][key]['category'] == c['correct_category']
        )
        accuracy = correct / len(model_cases)
        latencies = [
            c['models'][key]['latency_ms'] for c in model_cases if c['models'][key]['latency_ms']
        ]
        avg_latency = sum(latencies) / len(latencies) if latencies else 0
        avg_in = sum(c['models'][key]['input_tokens'] for c in model_cases) / len(model_cases)
        avg_out = sum(c['models'][key]['output_tokens'] for c in model_cases) / len(model_cases)
        cost = (avg_in / 1_000_000) * model['input_per_m'] + (avg_out / 1_000_000) * model[
            'output_per_m'
        ]

        print(
            f'  {model["label"]:<28} {accuracy:>5.1%}  {avg_latency:>9.0f}ms  '
            f'{avg_in:>6.0f}/{avg_out:<7.0f}  ${cost * 1000:.4f}'
        )

    print()
    print('FIXTURE BREAKDOWN\n')
    for case in labeled:
        correct_cat = case['correct_category']
        line = f'  {case["fixture"]:<48} label={correct_cat:<18}'
        for model in MODELS:
            key = model['key']
            got = case['models'].get(key, {}).get('category') or 'err'
            mark = '✓' if got == correct_cat else '✗'
            line += f'  {mark}{key}={got}'
        print(line)

    print()


# ── Entry ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    if '--score' in sys.argv:
        score()
    elif '--dry-run' in sys.argv:
        run_experiment(dry_run=True)
    else:
        run_experiment()
