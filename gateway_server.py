from __future__ import annotations

import asyncio
import logging
import os

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

GATEWAY_SECRET = os.getenv("HERMES_GATEWAY_SECRET", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
HERMES_BIN = "/root/.local/bin/hermes"


async def gateway(request: Request) -> JSONResponse:
    if GATEWAY_SECRET:
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {GATEWAY_SECRET}":
            return JSONResponse({"error": "unauthorized"}, status_code=401)

    data = await request.json()

    transaction_type = data.get("transaction_type", "transaction")
    amount = data.get("amount")
    currency = data.get("currency", "")
    merchant = data.get("merchant")
    date = str(data.get("date", ""))[:10]
    channel = data.get("channel", "")

    type_label = str(transaction_type).replace("_", " ").title()
    amount_str = f"{amount:,.0f}" if isinstance(amount, (int, float)) else str(amount or "")
    line2_parts = [f"{currency} {amount_str}".strip()]
    if merchant:
        line2_parts.append(merchant)
    if date:
        line2_parts.append(date)
    message = f"💳 *{type_label}*\n{' | '.join(line2_parts)}"

    log.info("dispatching to hermes type=%s amount=%s channel=%s", transaction_type, amount_str, channel)

    proc = await asyncio.create_subprocess_exec(
        HERMES_BIN, "send", "--to", f"telegram:{TELEGRAM_CHAT_ID}", message,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        log.error("hermes send failed: %s", stderr.decode())
        return JSONResponse({"error": "send failed"}, status_code=500)

    log.info("sent to telegram")
    return JSONResponse({"ok": True})


app = Starlette(routes=[Route("/gateway", gateway, methods=["POST"])])
