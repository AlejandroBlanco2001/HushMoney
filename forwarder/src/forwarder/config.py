from __future__ import annotations

import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
    load_dotenv()  # no-op if .env not present; only active when python-dotenv is installed (dev)
except ImportError:
    pass


@dataclass(frozen=True)
class ImapConfig:
    host: str
    port: int
    username: str
    password: str
    mailbox: str
    bank_senders: list[str]


@dataclass(frozen=True)
class Config:
    imap: ImapConfig
    hermes_gateway_url: str
    hermes_gateway_secret: str
    poll_interval_seconds: int
    dry_run: bool


def _require(key: str) -> str:
    value = os.environ.get(key, '').strip()
    if not value:
        raise RuntimeError(f'Required environment variable {key} is not set')
    return value


def _optional(key: str, default: str = '') -> str:
    return os.environ.get(key, '').strip() or default


def load() -> Config:
    senders = [s.strip() for s in _require('BANK_SENDER_EMAILS').split(',') if s.strip()]
    if not senders:
        raise RuntimeError('BANK_SENDER_EMAILS must contain at least one address')

    return Config(
        imap=ImapConfig(
            host=_require('IMAP_HOST'),
            port=int(_optional('IMAP_PORT', '993')),
            username=_require('IMAP_USERNAME'),
            password=_require('IMAP_PASSWORD'),
            mailbox=_optional('IMAP_MAILBOX', 'INBOX'),
            bank_senders=senders,
        ),
        hermes_gateway_url=_optional('HERMES_GATEWAY_URL'),
        hermes_gateway_secret=_optional('HERMES_GATEWAY_SECRET'),
        poll_interval_seconds=int(_optional('POLL_INTERVAL_SECONDS', '300')),
        dry_run=_optional('DRY_RUN', '').lower() in ('1', 'true', 'yes'),
    )
