from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sqlite3
import sys

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

GATEWAY_SECRET = os.getenv('HERMES_GATEWAY_SECRET', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')
HERMES_BIN = '/root/.local/bin/hermes'
DB_PATH = os.getenv('HUSHMONEY_DB', os.path.expanduser('~/.hermes/hushmoney.db'))

_SKILL_BASE = '/root/.hermes/skills/hushmoney'
_STORE_TX = f'{_SKILL_BASE}/expense_tracker/scripts/store_transaction.py'
_LOOKUP_CAT = f'{_SKILL_BASE}/categorizer/scripts/lookup_cached_category.py'
_SAVE_CAT = f'{_SKILL_BASE}/categorizer/scripts/save_category.py'
_CATEGORIZE = f'{_SKILL_BASE}/categorizer/scripts/categorize_merchant.py'
_SAVE_MERCHANT = f'{_SKILL_BASE}/categorizer/scripts/save_merchant.py'
_DETECT_RECURRING = f'{_SKILL_BASE}/categorizer/scripts/detect_recurring.py'
_MARK_RECURRING = f'{_SKILL_BASE}/categorizer/scripts/mark_recurring.py'

_NEBIUS_URL = (
    os.getenv('OPENAI_BASE_URL', 'https://api.studio.nebius.ai/v1/').rstrip('/')
    + '/chat/completions'
)
_NEBIUS_MODEL = os.getenv('HERMES_MODEL', 'nvidia/nemotron-3-super-120b-a12b')
_KEEPALIVE_INTERVAL = int(os.getenv('NEBIUS_KEEPALIVE_INTERVAL', '240'))


async def _run_script(*args: str) -> dict | None:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        log.warning(
            'script %s failed: %s', args[1] if len(args) > 1 else args[0], stderr.decode().strip()
        )
        return None
    try:
        return json.loads(stdout.decode())
    except (json.JSONDecodeError, ValueError):
        return None


async def _store_and_categorize(
    data: dict,
) -> tuple[str | None, str | None, bool, str | None, bool]:
    """Store transaction and attempt auto-categorization.

    Returns (tx_id, category, needs_clarification, last_category, is_recurring).
    needs_clarification=True means the merchant is ambiguous; category will be None
    and the caller should prompt the user.
    """
    args = [
        sys.executable,
        _STORE_TX,
        '--amount',
        str(data['amount']),
        '--currency',
        data['currency'],
        '--date',
        data['date'],
        '--transaction-type',
        data['transaction_type'],
        '--account-type',
        data['account_type'],
        '--channel',
        data['channel'],
        '--bank',
        data.get('bank', 'unknown'),
    ]
    if data.get('merchant'):
        args += ['--merchant', data['merchant']]
    if data.get('template_id'):
        args += ['--template-id', data['template_id']]
    if data.get('pattern_status'):
        args += ['--pattern-status', data['pattern_status']]

    result = await _run_script(*args)
    if not result or result.get('duplicate'):
        log.info('transaction duplicate or storage failed')
        return None, None, False, None, False

    tx_id = result.get('id')
    log.info('stored transaction %s', tx_id)

    merchant = data.get('merchant')
    if not tx_id or not merchant:
        return tx_id, None, False, None, False

    # 1. Check merchant cache.
    lookup = await _run_script(sys.executable, _LOOKUP_CAT, '--merchant', merchant)

    if lookup and lookup.get('found'):
        if lookup.get('needs_clarification'):
            log.info('merchant %s flagged needs_clarification', merchant)
            return tx_id, None, True, lookup.get('last_category'), False
        category = lookup.get('category')
        if category:
            await _run_script(sys.executable, _SAVE_CAT, '--id', tx_id, '--category', category)
            is_recurring = bool(lookup.get('is_recurring'))
            if is_recurring:
                await _run_script(sys.executable, _MARK_RECURRING, '--id', tx_id)
            log.info('cache hit %s → %s (recurring=%s)', merchant, category, is_recurring)
            return tx_id, category, False, None, is_recurring

    # 2. Cache miss — call LLM.
    log.info('cache miss for %s, calling LLM', merchant)
    cat_result = await _run_script(
        sys.executable,
        _CATEGORIZE,
        '--merchant',
        merchant,
        '--payload',
        json.dumps(data),
    )

    if not cat_result:
        return tx_id, None, False, None, False

    needs_clarification = cat_result.get('needs_clarification', False)
    category = cat_result.get('category') if not needs_clarification else None

    if category:
        await _run_script(sys.executable, _SAVE_CAT, '--id', tx_id, '--category', category)
        log.info('LLM categorized %s → %s', merchant, category)

    # 3. Detect recurring from transaction history.
    is_recurring = False
    if category:
        rec_result = await _run_script(sys.executable, _DETECT_RECURRING, '--merchant', merchant)
        if rec_result and rec_result.get('is_recurring'):
            is_recurring = True
            await _run_script(sys.executable, _MARK_RECURRING, '--id', tx_id)
            log.info(
                'recurring detected for %s (%d months)', merchant, rec_result.get('months_found', 0)
            )

    # Persist merchant so future transactions hit the cache.
    save_args = [sys.executable, _SAVE_MERCHANT, '--name', merchant]
    if category:
        save_args += ['--category', category]
    if needs_clarification:
        save_args += ['--needs-clarification']
    if is_recurring:
        save_args += ['--is-recurring']
    await _run_script(*save_args)

    return tx_id, category, needs_clarification, None, is_recurring


def _lookup_account_alias(bank: str, account_type: str, currency: str) -> str | None:
    """Return the registered account alias for this (bank, type, currency) triple."""
    try:
        con = sqlite3.connect(DB_PATH)
        row = con.execute(
            'SELECT alias FROM accounts WHERE bank = ? AND type = ? AND currency = ? LIMIT 1',
            (bank, account_type, currency),
        ).fetchone()
        con.close()
        return str(row[0]) if row and row[0] else None
    except Exception:
        return None


async def _keepalive_loop() -> None:
    api_key = os.getenv('NEBIUS_API_KEY') or os.getenv('OPENAI_API_KEY', '')
    payload = json.dumps(
        {
            'model': _NEBIUS_MODEL,
            'messages': [{'role': 'user', 'content': 'ping'}],
            'max_tokens': 1,
        }
    )
    while True:
        await asyncio.sleep(_KEEPALIVE_INTERVAL)
        try:
            proc = await asyncio.create_subprocess_exec(
                'curl',
                '-sf',
                '-X',
                'POST',
                _NEBIUS_URL,
                '-H',
                f'Authorization: Bearer {api_key}',
                '-H',
                'Content-Type: application/json',
                '-d',
                payload,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            log.info('nebius keepalive rc=%d', proc.returncode)
        except Exception as exc:
            log.warning('nebius keepalive failed: %s', exc)


@contextlib.asynccontextmanager
async def lifespan(_app: Starlette):
    task = asyncio.create_task(_keepalive_loop())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def gateway(request: Request) -> JSONResponse:
    if GATEWAY_SECRET:
        auth = request.headers.get('Authorization', '')
        if auth != f'Bearer {GATEWAY_SECRET}':
            return JSONResponse({'error': 'unauthorized'}, status_code=401)

    data = await request.json()

    transaction_type = data.get('transaction_type', 'transaction')
    amount = data.get('amount')
    currency = data.get('currency', '')
    merchant = data.get('merchant')
    date = str(data.get('date', ''))[:10]
    channel = data.get('channel', '')
    bank = data.get('bank', 'unknown')
    account_type = data.get('account_type', '')
    pattern_status = data.get('pattern_status', 'active')

    log.info(
        'incoming transaction type=%s amount=%s channel=%s bank=%s',
        transaction_type,
        amount,
        channel,
        bank,
    )

    # Store and auto-categorize
    tx_id, category, needs_clarification, last_category, is_recurring = await _store_and_categorize(
        data
    )

    # Build notification
    type_label = str(transaction_type).replace('_', ' ').title()
    amount_str = f'{amount:,.0f}' if isinstance(amount, (int, float)) else str(amount or '')
    parts = [f'{currency} {amount_str}'.strip()]
    if merchant:
        parts.append(merchant)
    if date:
        parts.append(date)

    alias = _lookup_account_alias(bank, account_type, currency)
    account_line = f' — {alias}' if alias else (f' — {bank.title()}' if bank != 'unknown' else '')

    candidate_marker = ' 🧪' if pattern_status == 'candidate' else ''
    message = f'💳 *{type_label}*{account_line}{candidate_marker}\n{" | ".join(parts)}'
    if category:
        recurring_marker = ' 🔄' if is_recurring else ''
        message += f'\n🏷️ {category.replace("_", " ").title()}{recurring_marker}'
    elif needs_clarification:
        suggestion = f' (last time: {last_category})' if last_category else ''
        message += f'\n❓ What was this {merchant} charge for?{suggestion}'

    proc = await asyncio.create_subprocess_exec(
        HERMES_BIN,
        'send',
        '--to',
        f'telegram:{TELEGRAM_CHAT_ID}',
        message,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        log.error('hermes send failed: %s', stderr.decode())
        return JSONResponse({'error': 'send failed'}, status_code=500)

    log.info('notification sent tx_id=%s', tx_id)
    return JSONResponse({'ok': True, 'tx_id': tx_id})


app = Starlette(lifespan=lifespan, routes=[Route('/gateway', gateway, methods=['POST'])])
