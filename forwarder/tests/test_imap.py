from __future__ import annotations

import email as email_lib
import textwrap
from pathlib import Path

import pytest

from forwarder.imap import (
    Email,
    _decode_header,
    _extract_plain_text,
    _resolve_original_sender,
    parse_email_bytes,
)


FIXTURES_DIR = Path(__file__).parent.parent.parent / 'tests' / 'fixtures' / 'emails' / 'bancolombia'

BANK_DOMAIN = 'notificacionesbancolombia.com'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_fixture(name: str) -> bytes:
    return (FIXTURES_DIR / name).read_bytes()


def _make_msg(headers: dict[str, str], body: str, content_type: str = 'text/plain') -> email_lib.message.Message:
    raw = ''
    for k, v in headers.items():
        raw += f'{k}: {v}\n'
    raw += f'Content-Type: {content_type}; charset=UTF-8\n'
    raw += f'MIME-Version: 1.0\n\n{body}'
    return email_lib.message_from_string(raw)


def _make_multipart(plain: str, html: str) -> email_lib.message.Message:
    raw = textwrap.dedent(f"""\
        MIME-Version: 1.0
        Content-Type: multipart/alternative; boundary="BOUND"

        --BOUND
        Content-Type: text/plain; charset=UTF-8

        {plain}
        --BOUND
        Content-Type: text/html; charset=UTF-8

        {html}
        --BOUND--
    """)
    return email_lib.message_from_string(raw)


# ---------------------------------------------------------------------------
# parse_email_bytes — fixture round-trips
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('fixture', [
    'compra_debito.eml',
    'pago_boton.eml',
    'transferencia_enviada.eml',
    'transferencia_recibida.eml',
    'retiro_atm.eml',
    'compra_credito.eml',
    'forwarded_auto.eml',
])
def test_parse_email_bytes_fixture(fixture: str) -> None:
    raw = _load_fixture(fixture)
    result = parse_email_bytes(raw)
    assert result is not None, f'{fixture}: expected a parsed Email, got None'
    assert isinstance(result, Email)
    assert result.subject, f'{fixture}: subject should not be empty'
    assert result.body, f'{fixture}: body should not be empty'


@pytest.mark.parametrize('fixture', [
    'compra_debito.eml',
    'pago_boton.eml',
    'transferencia_enviada.eml',
    'transferencia_recibida.eml',
    'retiro_atm.eml',
    'compra_credito.eml',
])
def test_parse_email_bytes_bank_sender(fixture: str) -> None:
    raw = _load_fixture(fixture)
    result = parse_email_bytes(raw)
    assert result is not None
    assert BANK_DOMAIN in result.from_, (
        f'{fixture}: expected bank domain in from_, got {result.from_!r}'
    )


def test_parse_email_bytes_forwarded_resolves_original_sender() -> None:
    raw = _load_fixture('forwarded_auto.eml')
    result = parse_email_bytes(raw)
    assert result is not None
    assert BANK_DOMAIN in result.from_, (
        f'forwarded_auto: expected original bank sender, got {result.from_!r}'
    )


def test_parse_email_bytes_no_body_returns_none() -> None:
    raw = b'From: bank@example.com\nSubject: Test\nContent-Type: text/html\n\n<p>html only</p>'
    assert parse_email_bytes(raw) is None


# ---------------------------------------------------------------------------
# _resolve_original_sender
# ---------------------------------------------------------------------------

def test_resolve_sender_direct_email() -> None:
    msg = _make_msg({'From': 'bank@example.com', 'Subject': 'Test'}, 'body')
    assert _resolve_original_sender(msg) == 'bank@example.com'


def test_resolve_sender_x_original_from() -> None:
    msg = _make_msg(
        {
            'From': 'forwarder@outlook.com',
            'X-Original-From': 'bank@example.com',
            'Subject': 'Fwd',
        },
        'body',
    )
    assert _resolve_original_sender(msg) == 'bank@example.com'


def test_resolve_sender_x_forwarded_from() -> None:
    msg = _make_msg(
        {
            'From': 'forwarder@gmail.com',
            'X-Forwarded-From': 'bank@example.com',
            'Subject': 'Fwd',
        },
        'body',
    )
    assert _resolve_original_sender(msg) == 'bank@example.com'


def test_resolve_sender_prefers_x_original_from_over_x_forwarded_from() -> None:
    msg = _make_msg(
        {
            'From': 'relay@example.com',
            'X-Original-From': 'original@bank.com',
            'X-Forwarded-From': 'other@relay.com',
            'Subject': 'Fwd',
        },
        'body',
    )
    assert _resolve_original_sender(msg) == 'original@bank.com'


# ---------------------------------------------------------------------------
# _extract_plain_text
# ---------------------------------------------------------------------------

def test_extract_plain_text_simple() -> None:
    msg = _make_msg({'From': 'a@b.com'}, 'Hello world')
    assert _extract_plain_text(msg) == 'Hello world'


def test_extract_plain_text_prefers_plain_over_html() -> None:
    msg = _make_multipart('Plain text content', '<p>HTML content</p>')
    text = _extract_plain_text(msg)
    assert 'Plain text content' in text
    assert '<p>' not in text


def test_extract_plain_text_html_only_returns_empty() -> None:
    raw = 'From: a@b.com\nContent-Type: text/html; charset=UTF-8\nMIME-Version: 1.0\n\n<p>html</p>'
    msg = email_lib.message_from_string(raw)
    assert _extract_plain_text(msg) == ''
