from __future__ import annotations

import json
import logging
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from starlette.testclient import TestClient

from forwarder.channels.telegram import COMMANDS, MAX_BODY_BYTES, create_app
from forwarder.channels.telegram import TelegramConfig


FIXTURES = Path(__file__).resolve().parents[2] / 'tests' / 'fixtures'
SECRET = 'synthetic-webhook-secret'
HEADERS = {'X-Telegram-Bot-Api-Secret-Token': SECRET}


@pytest.fixture
def cfg():
    return TelegramConfig(
        chat_id=123456789,
        webhook_secret=SECRET,
        gateway_secret='synthetic-gateway-secret',
        gateway_url='http://hermes:8080/gateway',
        hermes_webhook_url='http://hermes:8443/telegram',
        host='127.0.0.1',
        port=9000,
        timeout_seconds=2,
    )


@pytest.fixture
def update():
    return json.loads((FIXTURES / 'telegram/forwarded_purchase.json').read_text())


@pytest.fixture
def harness(cfg):
    requests = []

    def capture(request):
        requests.append(request)
        return httpx.Response(200)

    outbound = httpx.AsyncClient(transport=httpx.MockTransport(capture))
    with TestClient(create_app(cfg, outbound)) as client:
        yield client, requests


def test_forwarded_purchase_dispatches_only_clean_payload(harness, update, caplog):
    client, requests = harness
    with caplog.at_level(logging.INFO, logger='forwarder'):
        response = client.post('/telegram', json=update, headers=HEADERS)
    assert response.status_code == 200
    assert len(requests) == 1
    request = requests[0]
    expected = json.loads((FIXTURES / 'sms/bancolombia/compra_debito.expected.json').read_text())
    assert json.loads(request.content) == expected
    assert str(request.url) == 'http://hermes:8080/gateway'
    assert request.headers['authorization'] == 'Bearer synthetic-gateway-secret'
    assert 'x-telegram-bot-api-secret-token' not in request.headers
    for value in ('000000', '1234', 'MARIA', 'GARCIA', 'JUAN', SECRET):
        assert value not in request.content.decode()
        assert value not in caplog.text


def test_sms_relay_without_forward_metadata_is_sanitized(harness, update):
    del update['message']['forward_origin']
    client, requests = harness
    assert client.post('/telegram', json=update, headers=HEADERS).status_code == 200
    assert len(requests) == 1
    assert json.loads(requests[0].content)['channel'] == 'sms'


@pytest.mark.parametrize('command', sorted(COMMANDS))
def test_exact_command_routes_without_raw_metadata(harness, update, command):
    message = update['message']
    del message['forward_origin']
    message['text'] = command
    message['reply_to_message'] = {'text': 'OTP 000000 account 1234'}
    message['entities'] = [{'type': 'text_link', 'url': 'https://sensitive.example/1234'}]
    client, requests = harness
    assert client.post('/telegram', json=update, headers=HEADERS).status_code == 200
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == 'http://hermes:8443/telegram'
    assert request.headers['x-telegram-bot-api-secret-token'] == SECRET
    assert 'authorization' not in request.headers
    body = json.loads(request.content)
    assert body['message']['text'] == command
    assert body['message']['entities'][0]['type'] == 'bot_command'
    for sensitive in ('MARIA', 'GARCIA', '000000', 'reply_to_message', 'sensitive.example'):
        assert sensitive not in request.content.decode()


@pytest.mark.parametrize(
    'text',
    [
        '/help account 1234',
        '/help\nOTP 000000',
        '/help@another_bot',
        ' /help',
        'hermes cuenta 1234',
        'Hola',
        'OTP 000000',
        '',
    ],
)
def test_unrecognized_text_never_falls_through_to_chat(harness, update, text):
    del update['message']['forward_origin']
    update['message']['text'] = text
    client, requests = harness
    assert client.post('/telegram', json=update, headers=HEADERS).status_code == 200
    assert requests == []


def test_push_from_unknown_app_routed_to_learning(cfg):
    """Unknown-app push notifications are handed to UnmatchedHandler (redacted, no raw text)."""
    from forwarder.learning.unmatched import UnmatchedHandler
    from forwarder.learning.store import PatternStore
    import tempfile, pathlib

    captured: list[dict] = []

    class _FakeStore:
        def get_fingerprint(self, fp): return None
        def upsert_fingerprint(self, *a, **kw): pass
        def upsert_fingerprint_state(self, *a): pass

    class _CaptureHandler(UnmatchedHandler):
        def __init__(self):
            self._store = _FakeStore()
            self._hermes_url = cfg.hermes_webhook_url
            self._webhook_secret = cfg.webhook_secret

        async def handle_async(self, *, redacted_text, bank_slug, channel, status, **kw):
            captured.append({'text': redacted_text, 'bank': bank_slug, 'channel': channel})

    requests = []

    def capture(request):
        requests.append(request)
        return httpx.Response(200)

    outbound = httpx.AsyncClient(transport=httpx.MockTransport(capture))
    handler = _CaptureHandler()

    update = json.loads((FIXTURES / 'telegram/forwarded_purchase.json').read_text())
    del update['message']['forward_origin']
    # The account number 123456 (6 digits) must be redacted in the text sent to learning.
    update['message']['text'] = 'Rappipay: compra $32.500,00 cuenta 123456'

    with TestClient(create_app(cfg, outbound, unmatched_handler=handler)) as client:
        response = client.post('/telegram', json=update, headers=HEADERS)

    assert response.status_code == 200
    assert len(captured) == 1
    assert '123456' not in captured[0]['text']
    assert '[REDACTED]' in captured[0]['text']
    assert captured[0]['channel'] == 'sms'
    # Unmatched handler sends its own request; no direct gateway request here.
    assert requests == []


@pytest.mark.parametrize('metadata', ['forward_origin', 'forward_from', 'forward_date'])
def test_forwarded_commands_are_not_executed(harness, update, metadata):
    del update['message']['forward_origin']
    update['message'][metadata] = {}
    update['message']['text'] = '/help'
    client, requests = harness
    assert client.post('/telegram', json=update, headers=HEADERS).status_code == 200
    assert requests == []


@pytest.mark.parametrize(
    'mutation',
    [
        lambda u: u['message']['chat'].update(id=987654321),
        lambda u: u['message']['chat'].update(id='123456789'),
        lambda u: u['message']['chat'].update(type='group'),
        lambda u: u['message']['from'].update(id=987654321),
        lambda u: u['message']['from'].update(is_bot=True),
        lambda u: u['message'].update(via_bot={}),
        lambda u: u['message'].pop('from'),
        lambda u: u['message'].pop('text'),
        lambda u: u['message'].update(text=['/help']),
        lambda u: u['message'].update(text='x' * 4097),
        lambda u: u.update(update_id=True),
        lambda u: u['message'].update(date=-1),
        lambda u: u.update(edited_message=u.pop('message')),
    ],
)
def test_unauthorized_or_unsupported_updates_are_ignored(harness, update, mutation):
    mutation(update)
    client, requests = harness
    assert client.post('/telegram', json=update, headers=HEADERS).status_code == 200
    assert requests == []


@pytest.mark.parametrize('value', [None, [], 'text', 12, {}, {'message': []}])
def test_invalid_update_shapes_are_ignored(harness, value):
    client, requests = harness
    assert client.post('/telegram', content=json.dumps(value), headers=HEADERS).status_code == 200
    assert requests == []


@pytest.mark.parametrize('headers', [{}, {'X-Telegram-Bot-Api-Secret-Token': 'wrong'}])
def test_webhook_authentication_precedes_parsing(harness, headers):
    client, requests = harness
    assert client.post('/telegram', content=b'not JSON', headers=headers).status_code == 403
    assert requests == []


@pytest.mark.parametrize(
    ('body', 'status'),
    [
        (b'not JSON', 400),
        (b'\xff', 400),
        (b'[' * 2000, 400),
        (b'x' * (MAX_BODY_BYTES + 1), 413),
    ],
)
def test_bad_request_bodies_are_rejected(harness, body, status):
    client, requests = harness
    response = client.post('/telegram', content=body, headers=HEADERS)
    assert response.status_code == status
    assert requests == []
    assert body not in response.content


@pytest.mark.parametrize('command', [False, True])
@pytest.mark.parametrize('failure', ['timeout', 'connect', '500', '302'])
def test_dispatch_failure_is_dropped_without_retries_or_sensitive_logs(
    cfg,
    update,
    caplog,
    command,
    failure,
):
    requests = []
    if command:
        del update['message']['forward_origin']
        update['message']['text'] = '/help'

    def fail(request):
        requests.append(request)
        sensitive = f'{SECRET} account 1234 OTP 000000'
        if failure == 'timeout':
            raise httpx.ReadTimeout(sensitive, request=request)
        if failure == 'connect':
            raise httpx.ConnectError(sensitive, request=request)
        return httpx.Response(
            int(failure),
            text=sensitive,
            headers={'Location': 'https://untrusted.example'},
        )

    outbound = httpx.AsyncClient(transport=httpx.MockTransport(fail))
    with (
        caplog.at_level(logging.INFO, logger='forwarder'),
        TestClient(create_app(cfg, outbound)) as client,
    ):
        response = client.post('/telegram', json=update, headers=HEADERS)
    assert response.status_code == 200
    assert len(requests) == 1
    assert 'message dropped' in caplog.text
    assert SECRET not in caplog.text
    assert '000000' not in caplog.text
    assert '1234' not in caplog.text


def test_optional_gateway_auth_is_omitted(cfg, update):
    requests = []

    def capture(request):
        requests.append(request)
        return httpx.Response(200)

    outbound = httpx.AsyncClient(transport=httpx.MockTransport(capture))
    with TestClient(create_app(replace(cfg, gateway_secret=''), outbound)) as client:
        client.post('/telegram', json=update, headers=HEADERS)
    assert 'authorization' not in requests[0].headers
