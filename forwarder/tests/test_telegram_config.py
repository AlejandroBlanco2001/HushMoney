from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from forwarder.channels.telegram_config import load


CONFIG = Path(__file__).resolve().parents[2] / 'config/hermes.yaml'


@pytest.fixture
def environment(monkeypatch):
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '123456789')
    monkeypatch.setenv('TELEGRAM_WEBHOOK_SECRET', 'synthetic-secret')
    monkeypatch.setenv('HERMES_GATEWAY_SECRET', 'synthetic-gateway-secret')


def test_loads_committed_config_without_imap_credentials(environment, monkeypatch):
    monkeypatch.delenv('IMAP_HOST', raising=False)
    cfg = load(CONFIG)
    assert cfg.chat_id == 123456789
    assert cfg.hermes_webhook_url == 'http://hermes:8443/telegram'
    assert cfg.gateway_url == 'http://hermes:8080/gateway'
    assert cfg.port == 9000
    assert 'synthetic-secret' not in repr(cfg)
    assert 'synthetic-gateway-secret' not in repr(cfg)


@pytest.mark.parametrize(
    ('key', 'value'),
    [
        ('TELEGRAM_CHAT_ID', ''),
        ('TELEGRAM_CHAT_ID', '-100123'),
        ('TELEGRAM_CHAT_ID', 'sensitive-value'),
        ('TELEGRAM_WEBHOOK_SECRET', ''),
        ('TELEGRAM_WEBHOOK_SECRET', 'sensitive-value with spaces'),
    ],
)
def test_invalid_identity_or_secret_fails_without_echoing_values(
    environment,
    monkeypatch,
    key,
    value,
):
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError, match=key) as error:
        load(CONFIG)
    assert key in str(error.value)
    if value:
        assert value not in str(error.value)


@pytest.mark.parametrize(
    ('key', 'value'),
    [
        ('port', 0),
        ('port', True),
        ('timeout_seconds', float('inf')),
        ('timeout_seconds', -1),
        ('gateway_url', 'file:///private'),
        ('gateway_url', 'http://user:sensitive-value@host/gateway'),
        ('hermes_webhook_url', 'http://hermes:8443/wrong-path'),
        ('host', ''),
    ],
)
def test_invalid_settings_fail_closed(environment, tmp_path, key, value):
    document = yaml.safe_load(CONFIG.read_text())
    document['forwarder']['telegram'][key] = value
    path = tmp_path / 'hermes.yaml'
    path.write_text(yaml.safe_dump(document))
    with pytest.raises(ValueError, match='must') as error:
        load(path)
    assert 'sensitive-value' not in str(error.value)


@pytest.mark.parametrize('content', ['[', '[]', 'forwarder: []'])
def test_invalid_config_reports_no_contents(environment, tmp_path, content):
    path = tmp_path / 'hermes.yaml'
    path.write_text(content)
    with pytest.raises(ValueError, match='configuration'):
        load(path)
