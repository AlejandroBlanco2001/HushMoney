from __future__ import annotations

import logging
import re
from dataclasses import replace
from datetime import UTC
from pathlib import Path

import pytest

from forwarder import sanitizer
from forwarder.imap import parse_email_bytes
from forwarder.sanitizer.banks import BANCOLOMBIA, TransactionPattern
from forwarder.sanitizer.selector import BankSelector


TEXT = (
    'Bancolombia: Compraste $32.500,00 en UBER RIDES con tu T.Deb *1234, el 15/09/2026 a las 20:35.'
)


@pytest.mark.parametrize(
    'sender',
    [
        'alertasynotificaciones@ayn.notificacionesbancolombia.com',
        'Bancolombia <ALERTASYNOTIFICACIONES@AYN.NOTIFICACIONESBANCOLOMBIA.COM>',
        'alertasynotificaciones@an.notificacionesbancolombia.com',
    ],
)
def test_known_sender_selects_bank_without_a_body_prefix(sender):
    payload = sanitizer.sanitize(TEXT.removeprefix('Bancolombia: '), 'email', sender=sender)
    assert payload is not None
    assert payload.amount == 32500


@pytest.mark.parametrize(
    'sender',
    [
        'unknown@example.com',
        'Bancolombia <unknown@example.com>',
        'alertasynotificaciones@ayn.notificacionesbancolombia.com.attacker.example',
        '',
    ],
)
def test_unknown_sender_does_not_fall_back_to_bank_name(sender, caplog):
    with caplog.at_level(logging.INFO):
        assert sanitizer.sanitize(TEXT, 'email', sender=sender) is None
    assert TEXT not in caplog.text
    if sender:
        assert sender not in caplog.text


def test_forwarded_email_uses_resolved_sender_without_logging_it(caplog):
    path = (
        Path(__file__).resolve().parents[2] / 'tests/fixtures/emails/bancolombia/forwarded_auto.eml'
    )
    with caplog.at_level(logging.INFO):
        message = parse_email_bytes(path.read_bytes())
        assert message is not None
        payload = sanitizer.sanitize(message.body, 'email', sender=message.from_)
    assert payload is not None
    assert payload.amount == 47350
    assert message.from_ not in caplog.text
    assert message.body not in caplog.text


def test_new_bank_only_needs_a_definition_and_registry_entry(monkeypatch):
    bank = replace(
        BANCOLOMBIA,
        name='synthetic-bank',
        email_senders=frozenset({'alerts@synthetic.example'}),
        prefix=re.compile(r'Synthetic:'),
        currency='USD',
        thousands_separator=',',
        decimal_separator='.',
        local_timezone=UTC,
        transactions=(
            TransactionPattern(
                'debit',
                re.compile(r'Paid \$(?P<amount>[\d,]+\.\d{2}) at (?P<merchant>.+?) on'),
                account_type='savings',
            ),
        ),
    )
    monkeypatch.setattr(sanitizer, '_BANK_SELECTOR', BankSelector((BANCOLOMBIA, bank)))
    text = 'Synthetic: Paid $1,234.50 at EXITO on 15/09/2026 20:35. Verification code: 0000'
    for channel, sender in [('sms', None), ('email', 'alerts@synthetic.example')]:
        payload = sanitizer.sanitize(text, channel, sender=sender)
        assert payload is not None
        assert payload.to_json() == {
            'amount': 1234.5,
            'currency': 'USD',
            'merchant': 'EXITO',
            'date': '2026-09-15T20:35:00Z',
            'transaction_type': 'debit',
            'account_type': 'savings',
            'channel': channel,
        }
