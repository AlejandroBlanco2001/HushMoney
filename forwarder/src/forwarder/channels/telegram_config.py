from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

import yaml


@dataclass(frozen=True)
class TelegramConfig:
    chat_id: int
    webhook_secret: str = field(repr=False)
    gateway_secret: str = field(repr=False)
    gateway_url: str
    hermes_webhook_url: str
    host: str
    port: int
    timeout_seconds: float


def _required_secret(name: str) -> str:
    value = os.environ.get(name, '').strip()
    if not value:
        raise ValueError(f'{name} is required')
    return value


def _settings(path: Path) -> dict[str, object]:
    try:
        document: object = yaml.safe_load(path.read_text(encoding='utf-8'))
    except (OSError, yaml.YAMLError):
        raise ValueError('Cannot read Telegram configuration') from None
    for key in ('forwarder', 'telegram'):
        if not isinstance(document, dict):
            raise ValueError('Missing forwarder.telegram configuration')
        document = cast('dict[str, object]', document).get(key)
    if not isinstance(document, dict):
        raise ValueError('Missing forwarder.telegram configuration')
    return cast('dict[str, object]', document)


def _text(settings: dict[str, object], key: str) -> str:
    value = settings.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'forwarder.telegram.{key} must be a nonempty string')
    return value.strip()


def _url(settings: dict[str, object], key: str) -> str:
    value = _text(settings, key)
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme in ('http', 'https')
            and parsed.hostname
            and parsed.port != 0
            and not parsed.username
            and not parsed.password
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        raise ValueError(f'forwarder.telegram.{key} must be a valid HTTP URL') from None
    if not valid:
        raise ValueError(f'forwarder.telegram.{key} must be an HTTP URL without credentials')
    if key == 'hermes_webhook_url' and parsed.path != '/telegram':
        raise ValueError('Hermes webhook path must be /telegram')
    return value


def load(path: Path) -> TelegramConfig:
    settings = _settings(path)
    chat_id = _required_secret('TELEGRAM_CHAT_ID')
    if not re.fullmatch(r'[1-9][0-9]*', chat_id):
        raise ValueError('TELEGRAM_CHAT_ID must be a positive private chat ID')
    secret = _required_secret('TELEGRAM_WEBHOOK_SECRET')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,256}', secret):
        raise ValueError('TELEGRAM_WEBHOOK_SECRET must use Telegram secret-token characters')
    port = settings.get('port')
    timeout = settings.get('timeout_seconds')
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('forwarder.telegram.port must be between 1 and 65535')
    if type(timeout) not in (int, float) or not 0 < cast('float', timeout) <= 60:
        raise ValueError('forwarder.telegram.timeout_seconds must be between 0 and 60')
    return TelegramConfig(
        chat_id=int(chat_id),
        webhook_secret=secret,
        gateway_secret=os.environ.get('HERMES_GATEWAY_SECRET', '').strip(),
        gateway_url=_url(settings, 'gateway_url'),
        hermes_webhook_url=_url(settings, 'hermes_webhook_url'),
        host=_text(settings, 'host'),
        port=port,
        timeout_seconds=float(cast('float', timeout)),
    )
