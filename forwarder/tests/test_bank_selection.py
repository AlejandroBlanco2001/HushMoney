from __future__ import annotations

import logging
import re
from datetime import UTC
from pathlib import Path

import pytest

from forwarder import sanitizer
from forwarder.imap import parse_email_bytes
from forwarder.sanitizer import SanitizeStatus
from forwarder.sanitizer.banks import BankPatterns, TransactionPattern
from forwarder.sanitizer.registry import BANCOLOMBIA, RegistrySnapshot


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
    result = sanitizer.sanitize(TEXT.removeprefix('Bancolombia: '), 'email', sender=sender)
    assert result.status == SanitizeStatus.MATCHED
    assert result.payload is not None
    assert result.payload.amount == 32500


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
        result = sanitizer.sanitize(TEXT, 'email', sender=sender)
    assert result.status != SanitizeStatus.MATCHED
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
        result = sanitizer.sanitize(message.body, 'email', sender=message.from_)
    assert result.status == SanitizeStatus.MATCHED
    assert result.payload is not None
    assert result.payload.amount == 47350
    assert message.from_ not in caplog.text
    assert message.body not in caplog.text


def test_new_bank_only_needs_a_definition_and_registry_entry(monkeypatch):
    synth_bank = BankPatterns(
        name='synthetic-bank',
        country='CO',
        email_senders=frozenset({'alerts@synthetic.example'}),
        sms_prefix=re.compile(r'Synthetic:'),
        date=BANCOLOMBIA.date,
        currency='USD',
        thousands_separator=',',
        decimal_separator='.',
        local_timezone=UTC,
        transactions=(
            TransactionPattern(
                'debit',
                re.compile(r'Paid \$(?P<amount>[\d,]+\.\d{2}) at (?P<merchant>.+?) on'),
                account_type='savings',
                template_id='synthetic-bank.debit',
            ),
        ),
    )
    snap = RegistrySnapshot(
        banks=(BANCOLOMBIA, synth_bank),
        by_sender={
            **sanitizer.REGISTRY.snapshot().by_sender,
            'alerts@synthetic.example': synth_bank,
        },
        version='test',
    )

    class _FakeRegistry:
        def snapshot(self) -> RegistrySnapshot:
            return snap

        def reload_if_changed(self) -> None:
            pass

    monkeypatch.setattr(sanitizer, 'REGISTRY', _FakeRegistry())

    text = 'Synthetic: Paid $1,234.50 at EXITO on 15/09/2026 20:35. Verification code: 0000'
    for channel, sender in [('sms', None), ('email', 'alerts@synthetic.example')]:
        result = sanitizer.sanitize(text, channel, sender=sender)
        assert result.status == SanitizeStatus.MATCHED
        assert result.payload is not None
        assert result.payload.to_json() == {
            'amount': 1234.5,
            'currency': 'USD',
            'merchant': 'EXITO',
            'date': '2026-09-15T20:35:00Z',
            'transaction_type': 'debit',
            'account_type': 'savings',
            'channel': channel,
            'bank': 'synthetic-bank',
        }
