from __future__ import annotations

import importlib.util
import pathlib
import sys
from types import ModuleType
from unittest.mock import AsyncMock

import pytest
from starlette.testclient import TestClient


def _load_gateway() -> ModuleType:
    """Load the repo-root gateway_server.py as a module (it is not part of the
    forwarder package — it shells out to skill scripts)."""
    path = pathlib.Path(__file__).parents[2] / 'gateway_server.py'
    spec = importlib.util.spec_from_file_location('gateway_server', path)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules['gateway_server'] = mod
    spec.loader.exec_module(mod)
    return mod


PAYLOAD = {
    'transaction_type': 'debit',
    'amount': 32500,
    'currency': 'COP',
    'merchant': 'EXITO',
    'date': '2026-09-15',
    'channel': 'email',
    'bank': 'bancolombia',
    'account_type': 'checking',
}


class _FakeProc:
    def __init__(self, returncode: int = 0, stderr: bytes = b'') -> None:
        self.returncode = returncode
        self._stderr = stderr

    async def communicate(self) -> tuple[bytes, bytes]:
        return b'', self._stderr


@pytest.fixture
def gw():
    return _load_gateway()


def test_rejects_missing_bearer(gw, monkeypatch):
    monkeypatch.setattr(gw, 'GATEWAY_SECRET', 'topsecret')
    resp = TestClient(gw.app).post('/gateway', json=PAYLOAD)
    assert resp.status_code == 401


def test_rejects_wrong_bearer(gw, monkeypatch):
    monkeypatch.setattr(gw, 'GATEWAY_SECRET', 'topsecret')
    resp = TestClient(gw.app).post(
        '/gateway', json=PAYLOAD, headers={'Authorization': 'Bearer wrong'}
    )
    assert resp.status_code == 401


def test_accepts_correct_bearer(gw, monkeypatch):
    monkeypatch.setattr(gw, 'GATEWAY_SECRET', 'topsecret')
    monkeypatch.setattr(
        gw, '_store_and_categorize', AsyncMock(return_value=(None, None, False, None, False))
    )
    monkeypatch.setattr(gw, '_lookup_account_alias', lambda *a: None)
    monkeypatch.setattr(gw.asyncio, 'create_subprocess_exec', AsyncMock(return_value=_FakeProc(0)))
    resp = TestClient(gw.app).post(
        '/gateway', json=PAYLOAD, headers={'Authorization': 'Bearer topsecret'}
    )
    assert resp.status_code == 200


def test_happy_path_returns_tx_id(gw, monkeypatch):
    monkeypatch.setattr(gw, 'GATEWAY_SECRET', '')  # auth disabled
    monkeypatch.setattr(
        gw, '_store_and_categorize', AsyncMock(return_value=('tx-1', 'food', False, None, False))
    )
    monkeypatch.setattr(gw, '_lookup_account_alias', lambda *a: None)
    send = AsyncMock(return_value=_FakeProc(0))
    monkeypatch.setattr(gw.asyncio, 'create_subprocess_exec', send)

    resp = TestClient(gw.app).post('/gateway', json=PAYLOAD)
    assert resp.status_code == 200
    assert resp.json() == {'ok': True, 'tx_id': 'tx-1'}
    # The notification message is the 5th positional arg to the hermes CLI.
    message = send.call_args.args[4]
    assert 'EXITO' in message
    assert 'Food' in message  # category rendered as a label


def test_needs_clarification_prompts_user(gw, monkeypatch):
    monkeypatch.setattr(gw, 'GATEWAY_SECRET', '')
    monkeypatch.setattr(
        gw, '_store_and_categorize', AsyncMock(return_value=('tx-2', None, True, 'food', False))
    )
    monkeypatch.setattr(gw, '_lookup_account_alias', lambda *a: None)
    send = AsyncMock(return_value=_FakeProc(0))
    monkeypatch.setattr(gw.asyncio, 'create_subprocess_exec', send)

    resp = TestClient(gw.app).post('/gateway', json=PAYLOAD)
    assert resp.status_code == 200
    message = send.call_args.args[4]
    assert 'What was this' in message
    assert 'last time: food' in message


def test_hermes_send_failure_returns_500(gw, monkeypatch):
    monkeypatch.setattr(gw, 'GATEWAY_SECRET', '')
    monkeypatch.setattr(
        gw, '_store_and_categorize', AsyncMock(return_value=('tx-3', None, False, None, False))
    )
    monkeypatch.setattr(gw, '_lookup_account_alias', lambda *a: None)
    monkeypatch.setattr(
        gw.asyncio, 'create_subprocess_exec', AsyncMock(return_value=_FakeProc(1, b'boom'))
    )

    resp = TestClient(gw.app).post('/gateway', json=PAYLOAD)
    assert resp.status_code == 500
    assert resp.json() == {'error': 'send failed'}
