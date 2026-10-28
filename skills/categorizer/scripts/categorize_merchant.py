"""
Categorize a merchant using the LLM.

Reads categories from SQLite (falls back to hardcoded list).
Uses OPENAI_BASE_URL + HERMES_MODEL + NEBIUS_API_KEY env vars.

Usage: python3 categorize_merchant.py --merchant "MCD" --payload '{"amount": 15.0, ...}'
Output: {"category": "food", "needs_clarification": false}
        {"category": null, "needs_clarification": true, "reason": "payment_gateway"}
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import ssl
import urllib.error
import urllib.request


DB_PATH = os.environ.get('HUSHMONEY_DB', os.path.expanduser('~/.hermes/hushmoney.db'))
API_BASE = os.environ.get('OPENAI_BASE_URL', 'https://api.studio.nebius.ai/v1').rstrip('/')
MODEL = os.environ.get('HERMES_MODEL', 'nvidia/nemotron-3-super-120b-a12b')

_FALLBACK_CATEGORIES = [
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


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    for candidate in [
        os.environ.get('NIX_SSL_CERT_FILE', ''),
        os.environ.get('SSL_CERT_FILE', ''),
        '/etc/ssl/certs/ca-certificates.crt',
        '/etc/ssl/certs/ca-bundle.crt',
    ]:
        if candidate and os.path.exists(candidate):
            ctx.load_verify_locations(cafile=candidate)
            break
    return ctx


def _get_categories() -> list[str]:
    try:
        con = sqlite3.connect(DB_PATH)
        rows = con.execute('SELECT slug FROM categories ORDER BY slug').fetchall()
        con.close()
        if rows:
            return [r[0] for r in rows]
    except Exception:  # noqa: S110  # best-effort DB read; falls back to defaults
        pass
    return _FALLBACK_CATEGORIES


def _make_prompt(categories: list[str]) -> str:
    cats = ', '.join(categories)
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
- Ride-hailing apps (Uber, Cabify, InDriver) → "transport"
- Streaming, gaming → "entertainment"
- Pharmacies, clinics → "health"
- Utility and telecom providers → "services"
- No merchant field → infer from transaction_type

Respond with only the JSON object, no explanation."""


def _extract_result(text: str, categories: list[str]) -> dict:
    def _parse(obj: dict) -> dict:
        cat = str(obj.get('category', 'other')).lower().strip()
        reason = str(obj.get('reason', ''))
        needs_clarification = cat == 'needs_clarification'
        return {
            'category': None if needs_clarification else cat,
            'needs_clarification': needs_clarification,
            'reason': reason,
        }

    try:
        return _parse(json.loads(text))
    except (json.JSONDecodeError, AttributeError):
        pass

    matches = re.findall(r'\{[^{}]*"category"\s*:[^{}]*\}', text)
    if matches:
        try:
            return _parse(json.loads(matches[-1]))
        except json.JSONDecodeError:
            m = re.search(r'"category"\s*:\s*"([^"]+)"', matches[-1])
            if m:
                return _parse({'category': m.group(1)})

    all_cats = [*categories, 'needs_clarification']
    for cat in all_cats:
        if re.search(rf'\b{re.escape(cat)}\b', text, re.IGNORECASE):
            return _parse({'category': cat})

    return {'category': 'other', 'needs_clarification': False, 'reason': ''}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--merchant', required=True)
    parser.add_argument('--payload', required=True, help='JSON transaction payload')
    args = parser.parse_args()

    api_key = os.environ.get('NEBIUS_API_KEY') or os.environ.get('OPENAI_API_KEY', '')
    if not api_key:
        print(
            json.dumps({'category': 'other', 'needs_clarification': False, 'reason': 'no_api_key'})
        )
        return

    categories = _get_categories()

    try:
        payload = json.loads(args.payload)
    except json.JSONDecodeError:
        payload = {'merchant': args.merchant}

    body = json.dumps(
        {
            'model': MODEL,
            'messages': [
                {'role': 'system', 'content': _make_prompt(categories)},
                {'role': 'user', 'content': json.dumps(payload)},
            ],
            'temperature': 0,
            'max_tokens': 64,
        }
    ).encode()

    req = urllib.request.Request(
        f'{API_BASE}/chat/completions',
        data=body,
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}',
        },
        method='POST',
    )

    try:
        with urllib.request.urlopen(req, timeout=15, context=_ssl_context()) as resp:
            data = json.loads(resp.read())
        message = data['choices'][0]['message']
        content = (message.get('content') or message.get('reasoning_content') or '').strip()
        result = _extract_result(content, categories)
    except Exception as exc:
        result = {'category': 'other', 'needs_clarification': False, 'reason': f'error: {exc}'}

    print(json.dumps(result))


if __name__ == '__main__':
    main()
