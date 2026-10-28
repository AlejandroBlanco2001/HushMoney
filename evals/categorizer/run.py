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
from lib import api
from lib import models as _models


REPO_ROOT = _models.REPO_ROOT
RESULTS_FILE = Path(__file__).parent / 'results.json'
GOLDEN_FILE = REPO_ROOT / 'skills/categorizer/evals/golden.jsonl'
MODELS = _models.MODELS

CATEGORIES = [
    'food',
    'transport',
    'entertainment',
    'health',
    'shopping',
    'services',
    'transfers',
    'cash',
    'other',
]

THRESHOLD = 0.80  # eval fails if overall accuracy drops below this


# ── Fixtures ───────────────────────────────────────────────────────────────────


@dataclass
class Fixture:
    name: str
    merchant: str | None
    payload: dict[str, Any]
    expected: str  # category slug or "needs_clarification"


def load_fixtures() -> list[Fixture]:
    fixtures = []
    for line in GOLDEN_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        fixtures.append(
            Fixture(
                name=row['name'],
                merchant=row.get('merchant'),
                payload=row['payload'],
                expected=row['expected'],
            )
        )
    return fixtures


# ── Prompt ─────────────────────────────────────────────────────────────────────


def _make_prompt() -> str:
    cats = ', '.join(CATEGORIES)
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
        api_key,
        model_id,
        messages=[
            {'role': 'system', 'content': _make_prompt()},
            {'role': 'user', 'content': json.dumps(fixture.payload)},
        ],
        max_tokens=64,
    )
    result = api.extract_json(resp['content'], valid_values=CATEGORIES + ['needs_clarification'])
    cat = str(result.get('category') or result.get('_scanned') or 'other').lower().strip()
    return {
        'category': cat,
        'reason': str(result.get('reason', '')),
        'correct': cat == fixture.expected,
        'latency_ms': resp['latency_ms'],
        'input_tokens': resp['input_tokens'],
        'output_tokens': resp['output_tokens'],
        'error': None,
    }


# ── Run ────────────────────────────────────────────────────────────────────────


def run(model_filter: str | None = None, dry_run: bool = False) -> None:
    fixtures = load_fixtures()

    if dry_run:
        print(f'[dry-run] {len(fixtures)} fixtures (from {GOLDEN_FILE.relative_to(REPO_ROOT)})\n')
        for f in fixtures:
            print(f'  {f.name:<40} expected={f.expected}')
        return

    api.load_dotenv()
    api_key = os.environ.get('NEBIUS_API_KEY', '')
    if not api_key:
        print('ERROR: NEBIUS_API_KEY not set', file=sys.stderr)
        sys.exit(1)

    models = [m for m in MODELS if model_filter is None or m['key'] == model_filter]
    if not models:
        print(
            f"ERROR: unknown model '{model_filter}' — choose: nano, super, ultra", file=sys.stderr
        )
        sys.exit(1)

    cases = [
        {'fixture': f.name, 'merchant': f.merchant, 'expected': f.expected, 'models': {}}
        for f in fixtures
    ]

    for model in models:
        print(f'\n{model["label"]}')
        print('-' * 50)
        for i, fixture in enumerate(fixtures):
            try:
                result = call_model(api_key, model['id'], fixture)
                cases[i]['models'][model['key']] = result
                mark = '✓' if result['correct'] else '✗'
                label = result['category']
                if result.get('reason'):
                    label += f' ({result["reason"]})'
                print(f'  {mark} {fixture.name:<38} {label:<28} {result["latency_ms"]:>5}ms')
            except Exception as e:
                cases[i]['models'][model['key']] = {
                    'category': None,
                    'reason': '',
                    'correct': False,
                    'latency_ms': None,
                    'input_tokens': 0,
                    'output_tokens': 0,
                    'error': str(e),
                }
                print(f'  ✗ {fixture.name:<38} ERROR: {e}')
            time.sleep(0.2)

    with RESULTS_FILE.open('w') as f:
        json.dump(cases, f, indent=2, ensure_ascii=False)

    print(f'\nResults written to {RESULTS_FILE.relative_to(REPO_ROOT)}')
    score(cases)


# ── Score ──────────────────────────────────────────────────────────────────────


def score(cases: list[dict] | None = None) -> None:
    if cases is None:
        if not RESULTS_FILE.exists():
            print('No results.json — run the experiment first.', file=sys.stderr)
            sys.exit(1)
        with RESULTS_FILE.open() as f:
            cases = json.load(f)

    total = len(cases)
    unambiguous = [c for c in cases if c['expected'] != 'needs_clarification']
    ambiguous = [c for c in cases if c['expected'] == 'needs_clarification']

    run_models = {k for c in cases for k in c['models']}
    models = [m for m in MODELS if m['key'] in run_models]

    print(f'\n{"=" * 72}')
    print(
        f'CATEGORIZER EVAL  ({total} fixtures: {len(unambiguous)} unambiguous, {len(ambiguous)} ambiguous)'
    )
    print(f'{"=" * 72}\n')

    print(
        f'  {"Model":<28} {"Overall":>7}  {"Unambiguous":>11}  {"Clarification":>13}  {"$/1K":>8}  {"Pass":>5}'
    )
    print(f'  {"-" * 76}')

    failed_models: list[str] = []

    for model in models:
        key = model['key']
        model_cases = [c for c in cases if key in c['models'] and not c['models'][key].get('error')]
        if not model_cases:
            print(f'  {model["label"]:<28}  no data')
            continue

        def acc(subset):
            if not subset:
                return float('nan')
            hits = [c for c in subset if key in c['models'] and c['models'][key].get('correct')]
            eligible = [
                c for c in subset if key in c['models'] and not c['models'][key].get('error')
            ]
            return len(hits) / len(eligible) if eligible else float('nan')

        overall = acc(model_cases)
        avg_in = sum(c['models'][key]['input_tokens'] for c in model_cases) / len(model_cases)
        avg_out = sum(c['models'][key]['output_tokens'] for c in model_cases) / len(model_cases)
        cost = (avg_in / 1_000_000) * model['input_per_m'] + (avg_out / 1_000_000) * model[
            'output_per_m'
        ]
        passes = overall >= THRESHOLD
        if not passes:
            failed_models.append(model['label'])

        print(
            f'  {model["label"]:<28} {overall:>7.1%}  '
            f'{acc(unambiguous):>11.1%}  {acc(ambiguous):>13.1%}  ${cost * 1000:>7.4f}'
            f'  {"✓" if passes else "✗ FAIL":>5}'
        )

    print(f'\n  {"Fixture":<40} {"Expected":<22}', end='')
    for m in models:
        print(f'  {m["key"]:>6}', end='')
    print()
    print(f'  {"-" * (66 + len(models) * 9)}')

    for case in cases:
        print(f'  {case["fixture"]:<40} {case["expected"]:<22}', end='')
        for m in models:
            key = m['key']
            if key not in case['models']:
                print(f'  {"—":>6}', end='')
                continue
            r = case['models'][key]
            if r.get('error'):
                print(f'  {"err":>6}', end='')
            else:
                mark = '✓' if r['correct'] else '✗'
                print(f'  {mark + r["category"][:5]:>6}', end='')
        print()

    print()

    if failed_models:
        print(
            f'FAILED: {", ".join(failed_models)} below {THRESHOLD:.0%} threshold', file=sys.stderr
        )
        sys.exit(1)


# ── Entry ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', default=None, help='nano | super | ultra')
    parser.add_argument('--score', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    if args.score:
        score()
    elif args.dry_run:
        run(dry_run=True)
    else:
        run(model_filter=args.model)
