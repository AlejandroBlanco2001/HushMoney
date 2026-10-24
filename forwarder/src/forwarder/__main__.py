from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

import uvicorn

from forwarder import config, hermes, imap
from forwarder.channels import telegram
from forwarder.sanitizer import SanitizeStatus, sanitize
from forwarder.sanitizer import registry as _registry_module


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s %(message)s',
)
log = logging.getLogger(__name__)

_HERMES_CONFIG = Path('config/hermes.yaml')
_FORWARDER_DB = Path(os.environ.get('FORWARDER_DB_PATH', '/app/data/forwarder.db'))
_PATTERN_INBOX = Path(os.environ.get('FORWARDER_INBOX_DIR', '/app/pattern-inbox'))


def _setup_learning() -> tuple[object, object]:
    from forwarder.learning.inbox import InboxWatcher
    from forwarder.learning.store import PatternStore
    from forwarder.learning.unmatched import UnmatchedHandler

    _FORWARDER_DB.parent.mkdir(parents=True, exist_ok=True)
    store = PatternStore(_FORWARDER_DB)
    _registry_module.REGISTRY._store = store  # type: ignore[attr-defined]
    _registry_module.REGISTRY.reload_if_changed()

    try:
        tg_cfg = telegram.load(_HERMES_CONFIG)
        webhook_url = tg_cfg.hermes_webhook_url
        webhook_secret = tg_cfg.webhook_secret
    except ValueError:
        webhook_url = os.environ.get('HERMES_WEBHOOK_URL', '')
        webhook_secret = os.environ.get('TELEGRAM_WEBHOOK_SECRET', '')

    unmatched_handler = UnmatchedHandler(store, webhook_url, webhook_secret)
    watcher = InboxWatcher(_PATTERN_INBOX, store, _registry_module.REGISTRY)
    watcher.start()
    log.info('learning subsystem started db=%s inbox=%s', _FORWARDER_DB, _PATTERN_INBOX)
    return unmatched_handler, store


def _start_telegram_webhook(unmatched_handler: object) -> None:
    try:
        cfg = telegram.load(_HERMES_CONFIG)
    except ValueError as exc:
        log.warning('telegram webhook not started: %s', exc)
        return
    app = telegram.create_app(cfg, unmatched_handler=unmatched_handler)
    threading.Thread(
        target=uvicorn.run,
        kwargs={'app': app, 'host': cfg.host, 'port': cfg.port, 'access_log': False},
        daemon=True,
        name='telegram-webhook',
    ).start()
    log.info('telegram webhook listening on %s:%d', cfg.host, cfg.port)


def poll(cfg: config.Config, unmatched_handler: object) -> None:
    try:
        emails = imap.fetch_unread(cfg.imap)
    except Exception:
        log.exception('imap poll failed')
        return

    for e in emails:
        result = sanitize(e.body, channel='email', sender=e.from_)
        if result.status == SanitizeStatus.MATCHED and result.payload is not None:
            if cfg.dry_run:
                log.info('dry_run: would dispatch payload=%s', result.payload.to_json())
                continue
            try:
                hermes.dispatch(result.payload, cfg.hermes_gateway_url, cfg.hermes_gateway_secret)
            except Exception:
                log.exception('hermes dispatch failed')
        else:
            log.info('email unmatched status=%s', result.status)
            if unmatched_handler is not None:
                from forwarder.learning.unmatched import UnmatchedHandler

                assert isinstance(unmatched_handler, UnmatchedHandler)
                unmatched_handler.handle(
                    redacted_text=result.redacted_text,
                    bank_slug=result.bank_slug,
                    channel='email',
                    status=result.status,
                )


def main() -> None:
    unmatched_handler, _store = _setup_learning()
    _start_telegram_webhook(unmatched_handler)
    cfg = config.load()
    log.info(
        'forwarder started host=%s mailbox=%s senders=%s interval=%ds dry_run=%s',
        cfg.imap.host,
        cfg.imap.mailbox,
        cfg.imap.bank_senders,
        cfg.poll_interval_seconds,
        cfg.dry_run,
    )

    while True:
        poll(cfg, unmatched_handler)
        time.sleep(cfg.poll_interval_seconds)


if __name__ == '__main__':
    main()
