from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import httpx
import pytest

from forwarder.hermes import dispatch
from forwarder.sanitizer.models import CleanPayload


GATEWAY_URL = 'http://hermes:8080/gateway'
GATEWAY_SECRET = 'test-secret'

PAYLOAD = CleanPayload(
    amount=45000.0,
    currency='COP',
    date=datetime(2026, 10, 20, 18, 0, 0, tzinfo=UTC),
    transaction_type='debit',
    account_type='checking',
    channel='email',
    merchant='RAPPI',
)


def _mock_response(status_code: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            'error', request=MagicMock(), response=resp
        )
    return resp


def test_dispatch_sends_correct_payload() -> None:
    with patch('httpx.post', return_value=_mock_response()) as mock_post:
        dispatch(PAYLOAD, GATEWAY_URL, GATEWAY_SECRET)

    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    body = kwargs['json']
    assert body['amount'] == 45000.0
    assert body['currency'] == 'COP'
    assert body['transaction_type'] == 'debit'
    assert body['merchant'] == 'RAPPI'
    assert body['channel'] == 'email'
    assert kwargs['headers']['Authorization'] == f'Bearer {GATEWAY_SECRET}'


def test_dispatch_omits_auth_header_when_no_secret() -> None:
    with patch('httpx.post', return_value=_mock_response()) as mock_post:
        dispatch(PAYLOAD, GATEWAY_URL, '')

    _, kwargs = mock_post.call_args
    assert 'Authorization' not in kwargs['headers']


def test_dispatch_raises_on_http_error() -> None:
    with patch('httpx.post', return_value=_mock_response(500)):
        with pytest.raises(httpx.HTTPStatusError):
            dispatch(PAYLOAD, GATEWAY_URL, GATEWAY_SECRET)


def test_dispatch_raises_on_connection_error() -> None:
    with patch('httpx.post', side_effect=httpx.ConnectError('refused')):
        with pytest.raises(httpx.ConnectError):
            dispatch(PAYLOAD, GATEWAY_URL, GATEWAY_SECRET)


def test_dispatch_payload_without_merchant() -> None:
    payload_no_merchant = CleanPayload(
        amount=100.0,
        currency='COP',
        date=datetime(2026, 10, 20, tzinfo=UTC),
        transaction_type='cash',
        account_type='checking',
        channel='email',
        merchant=None,
    )
    with patch('httpx.post', return_value=_mock_response()) as mock_post:
        dispatch(payload_no_merchant, GATEWAY_URL, GATEWAY_SECRET)

    _, kwargs = mock_post.call_args
    assert 'merchant' not in kwargs['json']
