#!/usr/bin/env python3
"""
Model selection experiment for Hermes categorizer.

Sends each fixture's clean payload to every selected model, records the predicted
category, latency, and token usage, then scores accuracy against the labels.

By default it runs the pre-labeled golden set (golden_co.jsonl, 47 real Colombian
merchants) and scores automatically — no manual labeling step. Pass --fixtures to use
the unlabeled tests/fixtures instead (then fill correct_category and run --score).

Candidates are the Nebius cloud tiers plus the most prominent local SLMs served via
Ollama (Llama, Qwen, Gemma — see evals/lib/models.py). This lets you benchmark a
model that fits a normal 8-16GB-VRAM PC against the current cloud Nemotron.

Usage:
    # Cloud: add NEBIUS_API_KEY to .env at the repo root (copy from .env.example)
    # Local: install Ollama + `make ollama-pull` to fetch the SLM candidates
    python evals/model_selection/run.py              # all candidates, golden set, auto-scored
    python evals/model_selection/run.py --local      # local Ollama SLMs only (no API key)
    python evals/model_selection/run.py --cloud      # Nebius tiers only
    python evals/model_selection/run.py --dry-run    # list fixtures, no API calls
    python evals/model_selection/run.py --fixtures   # legacy unlabeled tests/fixtures path
    python evals/model_selection/run.py -j 8         # fixtures per model run 8-at-a-time

Fixtures run concurrently per model (default 4); models stay sequential so a local
Ollama only holds one model in VRAM at a time. Raise -j for cloud, lower it if a
local model OOMs (also bounded by Ollama's OLLAMA_NUM_PARALLEL).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


sys.path.insert(0, str(Path(__file__).parent.parent))
from lib import api
from lib import models as _models


REPO_ROOT = _models.REPO_ROOT
RESULTS_FILE = Path(__file__).parent / 'results.json'
GOLDEN_CO = Path(__file__).parent / 'golden_co.jsonl'
OLLAMA_CONFIG_FILE = Path(__file__).parent / 'ollama_config.json'
CLOUD_MODELS = _models.MODELS
LOCAL_MODELS = _models.LOCAL_MODELS


def load_ollama_config() -> dict[str, Any]:
    """Generation options applied to local (Ollama) calls — JSON mode, max_tokens, etc."""
    if not OLLAMA_CONFIG_FILE.exists():
        return {}
    cfg = json.loads(OLLAMA_CONFIG_FILE.read_text())
    return {k: v for k, v in cfg.items() if not k.startswith('_')}  # drop _comment


OLLAMA_CONFIG = load_ollama_config()


def select_models(argv: list[str]) -> list[dict[str, Any]]:
    """Pick candidates from flags: --local (Ollama only), --cloud (Nebius only), else both."""
    if '--local' in argv:
        return LOCAL_MODELS
    if '--cloud' in argv:
        return CLOUD_MODELS
    return [*CLOUD_MODELS, *LOCAL_MODELS]


# Default category set shipped with the app — user can add/remove via Telegram.
# In production the categorizer skill reads this list from SQLite at call time.
STARTER_CATEGORIES = [
    'restaurants',
    'groceries',
    'delivery',
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

Uncertain case — the purchase purpose cannot be determined from the merchant name
alone. This covers payment gateways/processors (e.g. PayU, Stripe, Adyen, Rappi,
or any generic capital/financial services company) AND hypermarkets or warehouse
clubs that sell both groceries and general merchandise/electronics under one name:
{{"category": "needs_clarification", "reason": "payment_gateway"}}

Valid categories: {cats}

Rules:
- transaction_type "transfer_out" or "transfer_in" → always "transfer"
- transaction_type "cash" → always "cash"
- Supermarkets and grocery stores → "groceries"
- Restaurants, fast food, cafes, bakeries → "restaurants"
- Food delivery platforms → "delivery"
- Hypermarkets / warehouse clubs (groceries + electronics/general) → "needs_clarification"
- Ride-hailing apps → "transport"
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


def load_golden(path: Path = GOLDEN_CO) -> list[dict[str, Any]]:
    """Load the pre-labeled golden set — scoring is automatic, no manual step."""
    cases: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        cases.append(
            {
                'fixture': row['name'],
                'input': row['payload'],
                'correct_category': row['expected'],
                'models': {},
            }
        )
    return cases


# ── API ────────────────────────────────────────────────────────────────────────


def call_model(
    model: dict[str, Any],
    payload: dict[str, Any],
    api_key: str,
    categories: list[str] = STARTER_CATEGORIES,
) -> dict[str, Any]:
    is_local = bool(model.get('local'))
    cfg = OLLAMA_CONFIG if is_local else {}  # JSON mode + higher cap only for local SLMs
    resp = api.chat_completion(
        '' if is_local else api_key,  # Ollama needs no key
        model['id'],
        messages=[
            {'role': 'system', 'content': make_system_prompt(categories)},
            {'role': 'user', 'content': json.dumps(payload)},
        ],
        base_url=model.get('base_url'),
        max_tokens=cfg.get('max_tokens', 256),
        temperature=cfg.get('temperature', 0),
        response_format=cfg.get('response_format'),
        timeout=180 if is_local else 30,  # local gen + first-call model load is slower
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


def _run_one(model: dict[str, Any], case: dict[str, Any], api_key: str) -> dict[str, Any]:
    """Call one model on one fixture, never raising — errors become a result dict."""
    try:
        return call_model(model, case['input'], api_key)
    except urllib.error.HTTPError as e:
        err = f'HTTP {e.code}: {e.reason}'
    except Exception as e:
        err = str(e)
    return {
        'category': None,
        'reason': '',
        'latency_ms': None,
        'input_tokens': 0,
        'output_tokens': 0,
        'error': err,
    }


def run_experiment(
    models: list[dict[str, Any]],
    dry_run: bool = False,
    use_golden: bool = True,
    concurrency: int = 4,
) -> None:
    api_key = ''
    if dry_run:
        print('[dry-run: fixture discovery only, no API calls]\n')
    else:
        api.load_dotenv()
        api_key = os.environ.get('NEBIUS_API_KEY', '')
        if any(not m.get('local') for m in models) and not api_key:
            print(
                'ERROR: NEBIUS_API_KEY not set (needed for cloud models; use --local to skip)',
                file=sys.stderr,
            )
            sys.exit(1)

    cases = load_golden() if use_golden else discover_fixtures()
    src = GOLDEN_CO.name if use_golden else 'tests/fixtures'
    print(f'Found {len(cases)} fixtures ({src})\n')

    if dry_run:
        for case in cases:
            print(f'  {case["fixture"]}')
            for model in models:
                print(f'    [{model["key"]:5}] (skipped)')
        return

    # Models stay sequential (so a local Ollama holds one model in VRAM at a time),
    # but each model's fixtures run concurrently — the calls are almost all I/O wait.
    for model in models:
        print(f'\n{model["label"]}  (×{concurrency})')
        print('-' * 64)
        results: dict[int, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {
                pool.submit(_run_one, model, cases[i], api_key): i for i in range(len(cases))
            }
            for fut in as_completed(futures):
                results[futures[fut]] = fut.result()

        for i, case in enumerate(cases):
            r = results[i]
            case['models'][model['key']] = r
            if r.get('error'):
                print(f'  ✗ {case["fixture"]:<42} ERROR: {r["error"]}')
                continue
            label = r['category']
            if r.get('reason'):
                label = f'{label} ({r["reason"]})'
            mark = '✓' if r['category'] == case['correct_category'] else '✗'
            print(f'  {mark} {case["fixture"]:<42} {label:<28} {r["latency_ms"]:>6}ms')

    print()

    with RESULTS_FILE.open('w') as f:
        json.dump(cases, f, indent=2, ensure_ascii=False)
    print(f'Written to {RESULTS_FILE.relative_to(REPO_ROOT)}')

    if use_golden:
        # Labels ship with the golden set — score right away, no manual step.
        score(models)
    else:
        print()
        print('Next steps:')
        print('  1. Open results.json')
        print('  2. Fill in "correct_category" for each fixture')
        print('  3. Run:  python evals/model_selection/run.py --score --fixtures')


# ── Score ──────────────────────────────────────────────────────────────────────


def score(models: list[dict[str, Any]]) -> None:
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

    for model in models:
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
        for model in models:
            key = model['key']
            got = case['models'].get(key, {}).get('category') or 'err'
            mark = '✓' if got == correct_cat else '✗'
            line += f'  {mark}{key}={got}'
        print(line)

    print()


# ── Entry ──────────────────────────────────────────────────────────────────────


def _jobs_from_argv(argv: list[str], default: int = 4) -> int:
    """Parse `-j N` / `--jobs N` (fixtures run concurrently per model)."""
    for flag in ('-j', '--jobs'):
        if flag in argv:
            idx = argv.index(flag)
            if idx + 1 < len(argv):
                try:
                    return max(1, int(argv[idx + 1]))
                except ValueError:
                    pass
    return default


if __name__ == '__main__':
    selected = select_models(sys.argv)
    use_golden = '--fixtures' not in sys.argv  # default: labeled golden set, auto-scored
    jobs = _jobs_from_argv(sys.argv)
    if '--score' in sys.argv:
        score(selected)
    elif '--dry-run' in sys.argv:
        run_experiment(selected, dry_run=True, use_golden=use_golden)
    else:
        run_experiment(selected, use_golden=use_golden, concurrency=jobs)
