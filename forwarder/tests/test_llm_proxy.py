from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
from collections.abc import AsyncIterator
from types import ModuleType
from typing import Any

import httpx
import pytest
from starlette.testclient import TestClient


def _load_proxy() -> ModuleType:
    """Load the repo-root llm_proxy.py as a module (it is not part of the forwarder
    package — it ships standalone inside the hermes container)."""
    path = pathlib.Path(__file__).parents[2] / 'llm_proxy.py'
    spec = importlib.util.spec_from_file_location('llm_proxy', path)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules['llm_proxy'] = mod
    spec.loader.exec_module(mod)
    return mod


class _FakeResponse:
    def __init__(self, content: bytes, status_code: int = 200) -> None:
        self.content = content
        self.status_code = status_code
        self.headers = {'content-type': 'application/json'}


class _FakeStreamResponse:
    def __init__(self, chunks: list[bytes], status_code: int = 200) -> None:
        self._chunks = chunks
        self.status_code = status_code
        self.headers = {'content-type': 'text/event-stream'}
        self.closed = False

    async def aiter_bytes(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


class _FakeClient:
    """Captures the forwarded request and returns a canned upstream response."""

    def __init__(self, response: Any = None, *, raise_error: bool = False) -> None:
        self._response = response
        self._raise = raise_error
        self.last_headers: dict[str, str] = {}
        self.last_content: bytes = b''
        self.last_url: str = ''

    async def request(self, method: str, url: str, **kwargs: Any) -> Any:
        if self._raise:
            raise httpx.ConnectError('boom')
        self.last_url = url
        self.last_headers = kwargs['headers']
        self.last_content = kwargs['content']
        return self._response

    def build_request(self, method: str, url: str, **kwargs: Any) -> Any:
        self.last_url = url
        self.last_headers = kwargs['headers']
        self.last_content = kwargs['content']
        return object()

    async def send(self, _req: Any, *, stream: bool) -> Any:
        if self._raise:
            raise httpx.ConnectError('boom')
        return self._response


@pytest.fixture
def proxy():
    return _load_proxy()


def _capture_events(proxy: ModuleType) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    proxy._record = events.append  # type: ignore[attr-defined]
    return events


def test_non_stream_records_tokens_latency_and_operation(proxy, monkeypatch):
    upstream_body = json.dumps(
        {
            'choices': [{'message': {'content': 'food'}}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15},
        }
    ).encode()
    fake = _FakeClient(_FakeResponse(upstream_body))
    monkeypatch.setattr(proxy, '_client', fake)
    events = _capture_events(proxy)

    resp = TestClient(proxy.app).post(
        '/v1/chat/completions',
        content=json.dumps({'model': 'nvidia/nemotron', 'stream': False}),
        headers={'Content-Type': 'application/json', 'X-Hermes-Op': 'categorizer'},
    )

    assert resp.status_code == 200
    assert resp.content == upstream_body  # body passed through untouched
    assert len(events) == 1
    event = events[0]
    assert event['operation'] == 'categorizer'
    assert event['model'] == 'nvidia/nemotron'
    assert event['prompt_tokens'] == 10
    assert event['completion_tokens'] == 5
    assert event['total_tokens'] == 15
    assert event['streamed'] is False
    assert isinstance(event['latency_ms'], int)


def test_op_header_stripped_before_forwarding(proxy, monkeypatch):
    fake = _FakeClient(_FakeResponse(b'{}'))
    monkeypatch.setattr(proxy, '_client', fake)
    _capture_events(proxy)

    TestClient(proxy.app).post(
        '/v1/chat/completions',
        content=json.dumps({'model': 'm'}),
        headers={'Content-Type': 'application/json', 'X-Hermes-Op': 'categorizer'},
    )

    assert 'x-hermes-op' not in {k.lower() for k in fake.last_headers}


def test_untagged_call_attributed_to_agent(proxy, monkeypatch):
    fake = _FakeClient(_FakeResponse(b'{"usage": {"total_tokens": 3}}'))
    monkeypatch.setattr(proxy, '_client', fake)
    events = _capture_events(proxy)

    TestClient(proxy.app).post(
        '/v1/chat/completions',
        content=json.dumps({'model': 'm'}),
        headers={'Content-Type': 'application/json'},
    )

    assert events[0]['operation'] == 'agent'


def test_stream_extracts_usage_and_ttft(proxy, monkeypatch):
    usage = json.dumps({'prompt_tokens': 7, 'completion_tokens': 2, 'total_tokens': 9})
    chunks = [
        b'data: {"choices": [{"delta": {"content": "hi"}}]}\n\n',
        f'data: {{"choices": [], "usage": {usage}}}\n\n'.encode(),
        b'data: [DONE]\n\n',
    ]
    fake = _FakeClient(_FakeStreamResponse(chunks))
    monkeypatch.setattr(proxy, '_client', fake)
    events = _capture_events(proxy)

    resp = TestClient(proxy.app).post(
        '/v1/chat/completions',
        content=json.dumps({'model': 'm', 'stream': True}),
        headers={'Content-Type': 'application/json'},
    )

    assert resp.status_code == 200
    assert b'[DONE]' in resp.content  # stream relayed through
    # stream_options.include_usage injected into the forwarded body
    assert json.loads(fake.last_content)['stream_options'] == {'include_usage': True}
    assert len(events) == 1
    event = events[0]
    assert event['streamed'] is True
    assert event['total_tokens'] == 9
    assert isinstance(event['ttft_ms'], int)


def test_upstream_error_returns_502_fail_open(proxy, monkeypatch):
    fake = _FakeClient(raise_error=True)
    monkeypatch.setattr(proxy, '_client', fake)
    events = _capture_events(proxy)

    resp = TestClient(proxy.app).post(
        '/v1/chat/completions',
        content=json.dumps({'model': 'm'}),
        headers={'Content-Type': 'application/json'},
    )

    assert resp.status_code == 502
    assert events == []  # nothing recorded when the call never completed


def test_non_chat_path_is_not_recorded(proxy, monkeypatch):
    fake = _FakeClient(_FakeResponse(b'{"data": []}'))
    monkeypatch.setattr(proxy, '_client', fake)
    events = _capture_events(proxy)

    resp = TestClient(proxy.app).get('/v1/models')

    assert resp.status_code == 200
    assert events == []  # only chat/completions calls are measured


async def test_emit_swallows_sink_errors(proxy, monkeypatch):
    class _BoomClient:
        async def post(self, *_args: Any, **_kwargs: Any) -> Any:
            raise httpx.ConnectError('sink down')

    monkeypatch.setattr(proxy, '_client', _BoomClient())
    monkeypatch.setattr(proxy, 'OPENOBSERVE_URL', 'http://obs:5080')

    # Must not raise — telemetry failures never surface.
    await proxy._emit({'total_tokens': 1})
