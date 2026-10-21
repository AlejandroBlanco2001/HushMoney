from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import uvicorn

from forwarder import config, hermes, imap
from forwarder.channels import telegram
from forwarder.sanitizer import sanitize


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s %(message)s',
)
log = logging.getLogger(__name__)

_HERMES_CONFIG = Path('config/hermes.yaml')


def _start_telegram_webhook() -> None:
    try:
        cfg = telegram.load(_HERMES_CONFIG)
    except ValueError as exc:
        log.warning('telegram webhook not started: %s', exc)
        return
    app = telegram.create_app(cfg)
    threading.Thread(
        target=uvicorn.run,
        kwargs={'app': app, 'host': cfg.host, 'port': cfg.port, 'access_log': False},
        daemon=True,
        name='telegram-webhook',
    ).start()
    log.info('telegram webhook listening on %s:%d', cfg.host, cfg.port)


def poll(cfg: config.Config) -> None:
    try:
        emails = imap.fetch_unread(cfg.imap)
    except Exception:
        log.exception('imap poll failed')
        return

    for e in emails:
        payload = sanitize(e.body, channel='email', sender=e.from_)
        if payload is None:
            log.info('pattern not matched, email dropped')
            continue
        try:
            hermes.dispatch(payload, cfg.hermes_gateway_url, cfg.hermes_gateway_secret)
        except Exception:
            log.exception('hermes dispatch failed')


def main() -> None:
    _start_telegram_webhook()
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
        poll(cfg)
        time.sleep(cfg.poll_interval_seconds)


if __name__ == '__main__':
    main()
