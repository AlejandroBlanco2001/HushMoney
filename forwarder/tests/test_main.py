from __future__ import annotations

import pytest

from forwarder import __main__ as entrypoint
from forwarder.config import Config, ImapConfig
from forwarder.imap import Email


@pytest.mark.parametrize(
    ('sender', 'expected_dispatches'),
    [
        ('alertasynotificaciones@ayn.notificacionesbancolombia.com', 1),
        ('unknown@example.com', 0),
    ],
)
def test_email_pipeline_routes_by_sender(monkeypatch, sender, expected_dispatches):
    message = Email(
        from_=sender,
        subject='Synthetic notification',
        body='Bancolombia: Compraste $32.500,00 en EXITO con tu T.Deb *1234, '
        'el 15/09/2026 a las 20:35.',
    )
    cfg = Config(
        imap=ImapConfig('localhost', 993, 'synthetic', 'synthetic', 'INBOX', [sender]),
        hermes_gateway_url='http://hermes/gateway',
        hermes_gateway_secret='',
        poll_interval_seconds=300,
        dry_run=False,
    )
    dispatched = []
    monkeypatch.setattr(entrypoint.imap, 'fetch_unread', lambda _: [message])
    monkeypatch.setattr(
        entrypoint.hermes, 'dispatch', lambda payload, *_: dispatched.append(payload)
    )
    entrypoint.poll(cfg)
    assert len(dispatched) == expected_dispatches
    if dispatched:
        assert dispatched[0].merchant == 'EXITO'
