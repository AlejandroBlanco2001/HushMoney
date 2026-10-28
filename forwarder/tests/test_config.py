from __future__ import annotations

import pytest

from forwarder import config


BASE_ENV = {
    'IMAP_HOST': 'imap.gmail.com',
    'IMAP_USERNAME': 'user@gmail.com',
    'IMAP_PASSWORD': 'app-password',
    'BANK_SENDER_EMAILS': 'alerts@bank.com',
}


def test_load_minimal(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in BASE_ENV.items():
        monkeypatch.setenv(k, v)
    for k in (
        'IMAP_PORT',
        'IMAP_MAILBOX',
        'POLL_INTERVAL_SECONDS',
        'DRY_RUN',
        'HERMES_GATEWAY_URL',
        'HERMES_GATEWAY_SECRET',
    ):
        monkeypatch.delenv(k, raising=False)

    cfg = config.load()

    assert cfg.imap.host == 'imap.gmail.com'
    assert cfg.imap.port == 993
    assert cfg.imap.username == 'user@gmail.com'
    assert cfg.imap.mailbox == 'INBOX'
    assert cfg.imap.bank_senders == ['alerts@bank.com']
    assert cfg.poll_interval_seconds == 300
    assert cfg.dry_run is False


def test_load_custom_port_and_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in BASE_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv('IMAP_PORT', '143')
    monkeypatch.setenv('POLL_INTERVAL_SECONDS', '60')

    cfg = config.load()

    assert cfg.imap.port == 143
    assert cfg.poll_interval_seconds == 60


def test_load_multiple_senders(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in BASE_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv('BANK_SENDER_EMAILS', 'a@bank.com, b@bank.com , c@bank.com')

    cfg = config.load()

    assert cfg.imap.bank_senders == ['a@bank.com', 'b@bank.com', 'c@bank.com']


def test_load_dry_run_variants(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in BASE_ENV.items():
        monkeypatch.setenv(k, v)

    for value in ('1', 'true', 'yes', 'True', 'YES'):
        monkeypatch.setenv('DRY_RUN', value)
        assert config.load().dry_run is True

    for value in ('0', 'false', '', 'no'):
        monkeypatch.setenv('DRY_RUN', value)
        assert config.load().dry_run is False


@pytest.mark.parametrize(
    'missing_key',
    [
        'IMAP_HOST',
        'IMAP_USERNAME',
        'IMAP_PASSWORD',
        'BANK_SENDER_EMAILS',
    ],
)
def test_load_missing_required_raises(monkeypatch: pytest.MonkeyPatch, missing_key: str) -> None:
    for k, v in BASE_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv(missing_key)

    with pytest.raises(RuntimeError, match=missing_key):
        config.load()


def test_load_empty_bank_senders_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in BASE_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv('BANK_SENDER_EMAILS', '  ,  ')

    with pytest.raises(RuntimeError, match='BANK_SENDER_EMAILS'):
        config.load()
