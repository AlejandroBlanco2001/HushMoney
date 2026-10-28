"""Nebius API helpers: dotenv loading, SSL, HTTP call, JSON extraction."""

from __future__ import annotations

import json
import os
import re
import ssl
import time
import urllib.request
from pathlib import Path
from typing import Any

from .models import API_BASE, REPO_ROOT


def load_dotenv(path: Path | None = None) -> None:
    """Load .env into os.environ (skips keys already set)."""
    path = path or (REPO_ROOT / '.env')
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, value = line.partition('=')
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    for candidate in [
        os.environ.get('NIX_SSL_CERT_FILE', ''),
        os.environ.get('SSL_CERT_FILE', ''),
        '/etc/ssl/certs/ca-certificates.crt',
        '/etc/ssl/certs/ca-bundle.crt',
    ]:
        if candidate and Path(candidate).exists():
            ctx.load_verify_locations(cafile=candidate)
            break
    return ctx


def chat_completion(
    api_key: str,
    model_id: str,
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 256,
    temperature: float = 0,
) -> dict[str, Any]:
    """Call the Nebius chat completions endpoint.

    Returns:
        {"content": str, "input_tokens": int, "output_tokens": int, "latency_ms": int}
    """
    body = json.dumps(
        {
            'model': model_id,
            'messages': messages,
            'temperature': temperature,
            'max_tokens': max_tokens,
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

    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=30, context=ssl_context()) as resp:
        latency_ms = round((time.perf_counter() - t0) * 1000)
        data = json.loads(resp.read())

    message = data['choices'][0]['message']
    content = (message.get('content') or message.get('reasoning_content') or '').strip()
    usage = data.get('usage', {})

    return {
        'content': content,
        'input_tokens': usage.get('prompt_tokens', 0),
        'output_tokens': usage.get('completion_tokens', 0),
        'latency_ms': latency_ms,
    }


def extract_json(text: str, valid_values: list[str] | None = None) -> dict[str, Any]:
    """Extract the last valid JSON object from model output.

    Handles flat and nested JSON, and reasoning models that prepend a monologue.
    Falls back to scanning for known values if JSON parsing fails entirely.
    valid_values: list of strings to scan for as a last resort (e.g. category slugs).
    """
    # Happy path: entire response is valid JSON
    try:
        return dict(json.loads(text))
    except (json.JSONDecodeError, AttributeError, TypeError):
        pass

    # Scan backwards for the last `{` that starts a valid JSON object.
    # Works for both flat and nested JSON, and skips reasoning-model preamble.
    pos = len(text)
    while True:
        pos = text.rfind('{', 0, pos)
        if pos == -1:
            break
        try:
            return dict(json.loads(text[pos:]))
        except (json.JSONDecodeError, TypeError):
            pass

    # Last resort: scan for any known value
    if valid_values:
        for value in valid_values:
            if re.search(rf'\b{re.escape(value)}\b', text, re.IGNORECASE):
                return {'_scanned': value}

    return {}
