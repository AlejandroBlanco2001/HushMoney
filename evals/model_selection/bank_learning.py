#!/usr/bin/env python3
"""
Bank-learning structural inference experiment.

Sends synthetic bank messages (based on documented real formats) to each NVIDIA
Nemotron tier and measures whether the model correctly extracts the structural
template — field positions, amount format, date format, PII markers — without
reproducing actual values.

This mirrors what the bank_learning skill does in reactive mode.

Sources for message formats:
  - HDFC card spend / UPI:
      github.com/akhilnarang/bank-sms-parser
      github.com/sarim2000/pennywiseai-tracker/pull/863
      github.com/saurabhgupta050890/transaction-sms-parser
  - Generic US/international:
      smscountry.com/blog/sms-templates-for-financial-services/
  - Bancolombia (Colombia):
      tests/fixtures/sms/bancolombia/ (this repo)

Usage:
    export NEBIUS_API_KEY=sk-...   (or set in .env)
    python evals/model_selection/bank_learning.py
"""

from __future__ import annotations

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
RESULTS_FILE = Path(__file__).parent / 'bank_learning_results.json'
MODELS = _models.MODELS


# ── Prompt ─────────────────────────────────────────────────────────────────────


def make_system_prompt(locale: str | None = None) -> str:
    locale_hint = (
        f'\nUser locale: {locale}. Use this to resolve date format ambiguity '
        f'(e.g. US → MM/DD/YYYY, most other countries → DD/MM/YYYY).'
        if locale
        else ''
    )
    return f"""You are analyzing the structure of a bank notification message.
Your job is to extract the MESSAGE TEMPLATE — not the values inside it.{locale_hint}

Respond with ONLY a JSON object describing the structure:
{{
  "bank_name": string,
  "amount": {{
    "currency_symbol": string,
    "symbol_position": "prefix" | "suffix",
    "thousands_separator": string,
    "decimal_separator": string
  }},
  "date_format": string,
  "transaction_keyword": string,
  "transaction_type": "debit" | "credit" | "transfer_out" | "transfer_in" | "payment",
  "account_indicator": string,
  "pii_fields": [string]
}}

For pii_fields use these labels: card_number, account_number, balance, phone_number,
person_name, upi_id, reference_number, otp.

Rules:
- Never reproduce the actual amounts, dates, names, or account numbers from the message
- Focus on HOW the data is formatted, not WHAT the values are
- transaction_keyword is the exact verb or phrase that signals the transaction type
- date_format: reproduce the exact separator characters from the message
  (e.g. "DD-MM-YYYY" for dashes, "DD/MM/YYYY" for slashes, "DD MMM YYYY" for month names)
- account_indicator describes the masking pattern, e.g. "last 4 digits after x"
- Preserve exact punctuation in currency_symbol, including trailing dots
  (write "Rs." not "Rs", write "R$" not "R $")
- Purchase/buy verbs in any language map to transaction_type "debit"
  (e.g. "Spent", "debited", "Compraste", "used", "charged")
- Bill payments and service fees map to transaction_type "payment"

Respond with only the JSON object, no explanation."""


# ── Test cases ─────────────────────────────────────────────────────────────────


@dataclass
class Check:
    field: str  # dot-notation path into the model's JSON, e.g. "amount.currency_symbol"
    expected: Any  # exact value, or list of required strings (subset check for pii_fields)
    note: str = ''


@dataclass
class BankLearningCase:
    scenario: str
    source: str
    message: str
    checks: list[Check]
    locale: str | None = None  # ISO country code from setup skill; disambiguates date format


CASES: list[BankLearningCase] = [
    # ── HDFC Bank India — card spend ──────────────────────────────────────────
    # Format source: github.com/akhilnarang/bank-sms-parser
    #                github.com/saurabhgupta050890/transaction-sms-parser
    BankLearningCase(
        scenario='hdfc_india_card_spend',
        source='github.com/akhilnarang/bank-sms-parser',
        locale='IN',
        message=(
            'Spent Rs.3,000.00 From HDFC Bank Card x1234 At AMAZON '
            'On 15-09-2026 14:32:00 Bal Rs.42,580.75 -HDFC Bank'
        ),
        checks=[
            Check('bank_name', 'HDFC Bank'),
            Check('amount.currency_symbol', 'Rs.', 'dot included in symbol'),
            Check('amount.symbol_position', 'prefix'),
            Check('amount.thousands_separator', ','),
            Check('amount.decimal_separator', '.'),
            Check(
                'date_format',
                'DD-MM-YYYY HH:MM:SS',
                '15-09-2026 14:32:00 — dashes, with time',
            ),
            Check('transaction_keyword', 'Spent'),
            Check('transaction_type', 'debit'),
            Check('pii_fields', ['card_number', 'balance'], 'subset check'),
        ],
    ),
    # ── HDFC Bank India — UPI debit ───────────────────────────────────────────
    # Format source: github.com/sarim2000/pennywiseai-tracker/pull/863
    BankLearningCase(
        scenario='hdfc_india_upi_debit',
        source='github.com/sarim2000/pennywiseai-tracker/pull/863',
        locale='IN',
        message=(
            'Rs.450.00 debited from A/c XX1234 on 28-09-26 to VPA merchant@upi. '
            'UPI Ref 426512345678. Avl Bal Rs.12,340.50 -HDFC Bank'
        ),
        checks=[
            Check('bank_name', 'HDFC Bank'),
            Check('amount.currency_symbol', 'Rs.'),
            Check('amount.symbol_position', 'prefix'),
            Check('amount.decimal_separator', '.'),
            Check('date_format', 'DD-MM-YY', '2-digit year: 28-09-26'),
            Check('transaction_keyword', 'debited'),
            Check('transaction_type', 'debit'),
            Check('pii_fields', ['account_number', 'balance'], 'subset check'),
        ],
    ),
    # ── Generic US/International ──────────────────────────────────────────────
    # Format source: smscountry.com/blog/sms-templates-for-financial-services/
    BankLearningCase(
        scenario='generic_us_debit',
        source='smscountry.com/blog/sms-templates-for-financial-services/',
        locale='US',
        message=(
            '[First National Bank] USD 1,250.00 debited from account ending 1234 '
            'on 09/15/2026. Merchant: WHOLE FOODS. '
            'Available balance: USD 3,842.10. '
            'Call 1-800-555-0123 if unauthorized.'
        ),
        checks=[
            Check('bank_name', 'First National Bank'),
            Check('amount.currency_symbol', 'USD'),
            Check('amount.symbol_position', 'prefix'),
            Check('amount.thousands_separator', ','),
            Check('amount.decimal_separator', '.'),
            Check('date_format', 'MM/DD/YYYY', 'US format: 09/15/2026'),
            Check('transaction_keyword', 'debited'),
            Check('transaction_type', 'debit'),
            Check(
                'pii_fields',
                ['account_number', 'balance', 'phone_number'],
                'subset check',
            ),
        ],
    ),
    # ── Bancolombia Colombia — debit purchase ─────────────────────────────────
    # Format source: tests/fixtures/sms/bancolombia/compra_debito.txt (this repo)
    BankLearningCase(
        scenario='bancolombia_co_compra_debito',
        source='tests/fixtures/sms/bancolombia/compra_debito.txt',
        locale='CO',
        message=(
            'Bancolombia: Compraste $32.500,00 en UBER RIDES con tu T.Deb *1234, '
            'el 15/09/2026 a las 20:35. '
            'Si tienes dudas, encuentranos aqui: 6045109095. Estamos cerca.'
        ),
        checks=[
            Check('bank_name', 'Bancolombia'),
            Check('amount.currency_symbol', '$'),
            Check('amount.symbol_position', 'prefix'),
            Check('amount.thousands_separator', '.', 'Colombian/European: dot thousands'),
            Check('amount.decimal_separator', ',', 'Colombian/European: comma decimal'),
            Check('date_format', 'DD/MM/YYYY', 'el 15/09/2026 format'),
            Check('transaction_keyword', 'Compraste'),
            Check('transaction_type', 'debit'),
            Check('pii_fields', ['card_number', 'phone_number'], 'subset check'),
        ],
    ),
]


# ── Scoring ────────────────────────────────────────────────────────────────────


def _get_nested(obj: Any, path: str) -> Any:
    for key in path.split('.'):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def score_response(parsed: dict[str, Any], checks: list[Check]) -> tuple[int, int, list[str]]:
    correct = 0
    misses: list[str] = []

    for check in checks:
        actual = _get_nested(parsed, check.field)
        if actual is None:
            misses.append(f'{check.field}: missing')
            continue

        if isinstance(check.expected, list):
            # subset check — all expected items must appear in the actual list
            actual_lower = [str(v).lower() for v in (actual if isinstance(actual, list) else [])]
            expected_lower = [v.lower() for v in check.expected]
            missing = [v for v in expected_lower if v not in actual_lower]
            if missing:
                misses.append(f'{check.field}: missing {missing} in {actual}')
            else:
                correct += 1
        else:
            expected_str = str(check.expected).lower()
            actual_str = str(actual).lower()
            if expected_str in actual_str or actual_str == expected_str:
                correct += 1
            else:
                misses.append(f'{check.field}: got {actual!r}, want {check.expected!r}')

    return correct, len(checks), misses


# ── API ────────────────────────────────────────────────────────────────────────


def call_model(
    api_key: str,
    model_id: str,
    message: str,
    locale: str | None = None,
) -> tuple[dict[str, Any], int, int, int]:
    resp = api.chat_completion(
        api_key,
        model_id,
        messages=[
            {'role': 'system', 'content': make_system_prompt(locale)},
            {'role': 'user', 'content': message},
        ],
        max_tokens=2048,
    )
    parsed = api.extract_json(resp['content'])
    return parsed, resp['latency_ms'], resp['input_tokens'], resp['output_tokens']


# ── Runner ─────────────────────────────────────────────────────────────────────


def run() -> None:
    api.load_dotenv()
    api_key = os.environ.get('NEBIUS_API_KEY', '')
    if not api_key:
        print('ERROR: NEBIUS_API_KEY not set', file=sys.stderr)
        sys.exit(1)

    results: list[dict[str, Any]] = []

    for case in CASES:
        print(f'\n  {case.scenario}  (source: {case.source})')
        row: dict[str, Any] = {
            'scenario': case.scenario,
            'source': case.source,
            'models': {},
        }

        for model in MODELS:
            try:
                parsed, latency_ms, in_tok, out_tok = call_model(
                    api_key,
                    model['id'],
                    case.message,
                    locale=case.locale,
                )
                correct, total, misses = score_response(parsed, case.checks)
                score_pct = correct / total if total else 0

                row['models'][model['key']] = {
                    'score': score_pct,
                    'correct': correct,
                    'total': total,
                    'misses': misses,
                    'latency_ms': latency_ms,
                    'input_tokens': in_tok,
                    'output_tokens': out_tok,
                    'parsed': parsed,
                    'error': None,
                }
                miss_summary = f'  misses: {misses}' if misses else '  all fields correct'
                print(
                    f'    [{model["key"]:5}] {correct}/{total} fields  '
                    f'{latency_ms:>5}ms  {in_tok}+{out_tok} tok{miss_summary}'
                )
            except Exception as e:
                row['models'][model['key']] = {
                    'score': 0,
                    'correct': 0,
                    'total': len(case.checks),
                    'misses': [],
                    'latency_ms': None,
                    'input_tokens': 0,
                    'output_tokens': 0,
                    'parsed': {},
                    'error': str(e),
                }
                print(f'    [{model["key"]:5}] ERROR: {e}')

            time.sleep(0.25)

        results.append(row)

    with RESULTS_FILE.open('w') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    _print_summary(results)
    print(f'\nFull results written to {RESULTS_FILE.relative_to(REPO_ROOT)}\n')


def _print_summary(results: list[dict[str, Any]]) -> None:
    print(f'\n{"=" * 72}')
    print(f'BANK LEARNING STRUCTURAL INFERENCE  ({len(results)} scenarios)')
    print(f'{"=" * 72}\n')

    print(f'  {"Model":<28} {"Avg field coverage":>20}  {"Avg latency":>11}  {"$/1K calls":>10}')
    print(f'  {"-" * 72}')

    for model in MODELS:
        key = model['key']
        model_rows = [
            r['models'][key]
            for r in results
            if key in r['models'] and not r['models'][key].get('error')
        ]
        if not model_rows:
            print(f'  {model["label"]:<28}  no data')
            continue

        avg_score = sum(r['score'] for r in model_rows) / len(model_rows)
        avg_correct = sum(r['correct'] for r in model_rows)
        avg_total = sum(r['total'] for r in model_rows)
        latencies = [r['latency_ms'] for r in model_rows if r['latency_ms']]
        avg_lat = sum(latencies) / len(latencies) if latencies else 0
        avg_in = sum(r['input_tokens'] for r in model_rows) / len(model_rows)
        avg_out = sum(r['output_tokens'] for r in model_rows) / len(model_rows)
        cost_per_1k = (
            (avg_in / 1_000_000) * model['input_per_m']
            + (avg_out / 1_000_000) * model['output_per_m']
        ) * 1000

        print(
            f'  {model["label"]:<28} {avg_score:>18.1%} ({avg_correct}/{avg_total} fields)'
            f'  {avg_lat:>9.0f}ms  ${cost_per_1k:.4f}'
        )

    print()
    print('SCENARIO BREAKDOWN\n')
    for row in results:
        print(f'  {row["scenario"]} (src: {row["source"]})')
        for model in MODELS:
            key = model['key']
            m = row['models'].get(key, {})
            if m.get('error'):
                print(f'    [{key:5}] ERROR')
                continue
            marks = f'{m["correct"]}/{m["total"]}'
            misses = ', '.join(m.get('misses', [])) or '—'
            print(f'    [{key:5}] {marks}  misses: {misses}')
        print()


if __name__ == '__main__':
    run()
