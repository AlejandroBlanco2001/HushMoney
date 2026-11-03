"""LLM observability proxy for HushMoney.

A transparent pass-through in front of the Nebius (OpenAI-compatible) API. Every LLM
caller inside the hermes container resolves its endpoint from OPENAI_BASE_URL; pointing
that at this proxy lets us measure token usage and latency for *all* calls — including
the opaque NousResearch `hermes` binary, which emits no telemetry of its own.

Only metadata (model, operation, token counts, latency, status) is ever recorded. Request
and response bodies are never read for content, never logged, and never sent to the sink —
see docs/rules/security.md and ADR-0002 (the proxy sees post-sanitizer agent prompts).

Observability is strictly best-effort: a sink or upstream-metadata error must never alter
the proxied response. Usage events are pushed to OpenObserve off the response path.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any, cast
from urllib.parse import urlsplit

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route


logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# Callers point their base_url (OPENAI_BASE_URL) at the proxy including the `/v1`
# segment, so the request path already carries it (e.g. `v1/chat/completions`). We
# therefore forward to the upstream ORIGIN only (scheme://host) + the full path, which
# avoids doubling `/v1` when NEBIUS_UPSTREAM_URL itself ends in `/v1`.
_upstream = urlsplit(os.getenv('NEBIUS_UPSTREAM_URL', 'https://api.studio.nebius.ai/v1/'))
NEBIUS_UPSTREAM_ORIGIN = f'{_upstream.scheme}://{_upstream.netloc}'
OPENOBSERVE_URL = os.getenv('OPENOBSERVE_URL', '').rstrip('/')
OPENOBSERVE_ORG = os.getenv('OPENOBSERVE_ORG', 'default')
OPENOBSERVE_STREAM = os.getenv('OPENOBSERVE_STREAM', 'llm_usage')
OPENOBSERVE_AUTH = os.getenv('OPENOBSERVE_AUTH', '')

# Operation hint set by the callers we own (categorizer, keepalive). The opaque agent
# runtime sends no hint, so its calls are attributed to 'agent'. Stripped before forward.
_OP_HEADER = 'x-hermes-op'
_UPSTREAM_TIMEOUT = 120.0

_client: httpx.AsyncClient | None = None
_tasks: set[asyncio.Task[None]] = set()

# Plain alias (not a 3.12 `type` statement): this module runs on the hermes
# container's Python 3.11, even though CI type-checks it on 3.12.
Usage = dict[str, int]


@contextlib.asynccontextmanager
async def lifespan(_app: Starlette) -> AsyncGenerator[None]:
    global _client
    _client = httpx.AsyncClient()
    try:
        yield
    finally:
        await _client.aclose()
        _client = None


def _zero_usage() -> Usage:
    return {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}


def _as_usage(usage: object) -> Usage:
    if not isinstance(usage, dict):
        return _zero_usage()
    data = cast('dict[str, Any]', usage)
    return {
        'prompt_tokens': int(data.get('prompt_tokens', 0) or 0),
        'completion_tokens': int(data.get('completion_tokens', 0) or 0),
        'total_tokens': int(data.get('total_tokens', 0) or 0),
    }


def _forward_headers(request: Request) -> dict[str, str]:
    """Copy inbound headers, dropping hop-by-hop fields and our internal op hint.

    content-length is dropped so httpx recomputes it for the re-serialized body.
    """
    skip = {'host', 'content-length', _OP_HEADER}
    return {k: v for k, v in request.headers.items() if k.lower() not in skip}


def _event(
    *,
    model: str,
    operation: str,
    status: int,
    latency_ms: int,
    usage: Usage,
    streamed: bool,
    ttft_ms: int | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        '_timestamp': int(time.time() * 1_000_000),
        'model': model,
        'operation': operation,
        'latency_ms': latency_ms,
        'streamed': streamed,
        'status': status,
        **usage,
    }
    if ttft_ms is not None:
        event['ttft_ms'] = ttft_ms
    return event


async def _emit(event: dict[str, Any]) -> None:
    """Push one usage event to OpenObserve. Best-effort; errors are swallowed."""
    if not OPENOBSERVE_URL or _client is None:
        return
    url = f'{OPENOBSERVE_URL}/api/{OPENOBSERVE_ORG}/{OPENOBSERVE_STREAM}/_json'
    headers = {'Content-Type': 'application/json'}
    if OPENOBSERVE_AUTH:
        headers['Authorization'] = OPENOBSERVE_AUTH
    try:
        await _client.post(url, json=[event], headers=headers, timeout=5.0)
    except Exception as exc:  # telemetry must never break the proxy
        log.debug('openobserve push failed: %s', exc)


def _record(event: dict[str, Any]) -> None:
    """Schedule an event push off the response path. No-op without a configured sink."""
    if not OPENOBSERVE_URL:
        return
    task = asyncio.create_task(_emit(event))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def _scan_stream_usage(chunk: bytes, state: dict[str, Any]) -> None:
    """Accumulate SSE bytes and capture `usage` from the terminal chunk.

    Network reads split SSE arbitrarily, so a buffer is carried across chunks and only
    complete `data:` lines are parsed.
    """
    state['buf'] += chunk.decode('utf-8', 'ignore')
    while '\n' in state['buf']:
        line, _, rest = state['buf'].partition('\n')
        state['buf'] = rest
        line = line.strip()
        if not line.startswith('data:'):
            continue
        payload = line[len('data:') :].strip()
        if not payload or payload == '[DONE]':
            continue
        try:
            obj = json.loads(payload)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict):
            usage = cast('dict[str, Any]', obj).get('usage')
            if usage is not None:
                state['usage'] = _as_usage(usage)


async def _proxy_simple(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes,
    *,
    model: str,
    operation: str,
    record: bool,
) -> Response:
    assert _client is not None
    t0 = time.perf_counter()
    try:
        upstream = await _client.request(
            method, url, content=body, headers=headers, timeout=_UPSTREAM_TIMEOUT
        )
    except httpx.HTTPError as exc:
        log.warning('upstream request failed: %s', exc)
        return JSONResponse({'error': 'upstream_unavailable'}, status_code=502)

    latency_ms = round((time.perf_counter() - t0) * 1000)
    content = upstream.content
    if record:
        usage = _zero_usage()
        with contextlib.suppress(json.JSONDecodeError, ValueError, TypeError):
            usage = _as_usage(json.loads(content).get('usage'))
        _record(
            _event(
                model=model,
                operation=operation,
                status=upstream.status_code,
                latency_ms=latency_ms,
                usage=usage,
                streamed=False,
            )
        )
    return Response(
        content=content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get('content-type'),
    )


async def _proxy_stream(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes,
    *,
    model: str,
    operation: str,
) -> Response:
    assert _client is not None
    t0 = time.perf_counter()
    req = _client.build_request(
        method, url, content=body, headers=headers, timeout=_UPSTREAM_TIMEOUT
    )
    try:
        upstream = await _client.send(req, stream=True)
    except httpx.HTTPError as exc:
        log.warning('upstream stream failed: %s', exc)
        return JSONResponse({'error': 'upstream_unavailable'}, status_code=502)

    state: dict[str, Any] = {'buf': '', 'usage': _zero_usage(), 'ttft_ms': None}

    async def relay() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream.aiter_bytes():
                if state['ttft_ms'] is None:
                    state['ttft_ms'] = round((time.perf_counter() - t0) * 1000)
                _scan_stream_usage(chunk, state)
                yield chunk
        finally:
            await upstream.aclose()
            _record(
                _event(
                    model=model,
                    operation=operation,
                    status=upstream.status_code,
                    latency_ms=round((time.perf_counter() - t0) * 1000),
                    usage=state['usage'],
                    streamed=True,
                    ttft_ms=state['ttft_ms'],
                )
            )

    return StreamingResponse(
        relay(),
        status_code=upstream.status_code,
        media_type=upstream.headers.get('content-type'),
    )


async def proxy(request: Request) -> Response:
    path = request.path_params['path']
    url = f'{NEBIUS_UPSTREAM_ORIGIN}/{path}'
    headers = _forward_headers(request)
    operation = request.headers.get(_OP_HEADER, 'agent')
    body = await request.body()

    parsed: dict[str, Any] | None = None
    if body:
        with contextlib.suppress(json.JSONDecodeError, ValueError):
            loaded = json.loads(body)
            if isinstance(loaded, dict):
                parsed = cast('dict[str, Any]', loaded)

    is_chat = path.endswith('chat/completions')
    model = str(parsed.get('model', '')) if parsed else ''

    if is_chat and parsed is not None and parsed.get('stream'):
        # Ask the upstream to include a usage block in the terminal SSE chunk.
        raw_opts = parsed.get('stream_options')
        opts: dict[str, Any] = (
            cast('dict[str, Any]', raw_opts) if isinstance(raw_opts, dict) else {}
        )
        opts = {**opts, 'include_usage': True}
        parsed['stream_options'] = opts
        body = json.dumps(parsed).encode()
        return await _proxy_stream(
            request.method, url, headers, body, model=model, operation=operation
        )

    return await _proxy_simple(
        request.method, url, headers, body, model=model, operation=operation, record=is_chat
    )


app = Starlette(
    lifespan=lifespan,
    routes=[
        Route(
            '/{path:path}',
            proxy,
            methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
        )
    ],
)
