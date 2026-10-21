from __future__ import annotations

import asyncio
import contextlib
import json
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

_NEBIUS_URL = (os.getenv("OPENAI_BASE_URL", "https://api.studio.nebius.ai/v1/").rstrip("/")
               + "/chat/completions")
_NEBIUS_MODEL = os.getenv("HERMES_MODEL", "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B")
_KEEPALIVE_INTERVAL = int(os.getenv("NEBIUS_KEEPALIVE_INTERVAL", "240"))


async def _keepalive_loop() -> None:
    api_key = os.getenv("NEBIUS_API_KEY") or os.getenv("OPENAI_API_KEY", "")
    payload = json.dumps({
        "model": _NEBIUS_MODEL,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    })
    while True:
        await asyncio.sleep(_KEEPALIVE_INTERVAL)
        try:
            proc = await asyncio.create_subprocess_exec(
                "curl", "-sf", "-X", "POST", _NEBIUS_URL,
                "-H", f"Authorization: Bearer {api_key}",
                "-H", "Content-Type: application/json",
                "-d", payload,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            log.info("nebius keepalive rc=%d", proc.returncode)
        except Exception as exc:
            log.warning("nebius keepalive failed: %s", exc)


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


app = Starlette(lifespan=lifespan, routes=[Route("/gateway", gateway, methods=["POST"])])
