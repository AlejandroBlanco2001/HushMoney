from __future__ import annotations

import logging
import time

from forwarder import config, hermes, imap


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s %(message)s',
)
log = logging.getLogger(__name__)


def poll(cfg: config.Config) -> None:
    try:
        emails = imap.fetch_unread(cfg.imap)
    except Exception:
        log.exception('imap poll failed')
        return

    for e in emails:
        log.info('email | from=%s | subject=%s | body=%s', e.from_, e.subject, e.body)
        if cfg.dry_run:
            log.info('[dry-run] skipping hermes dispatch')
            continue
        try:
            hermes.dispatch(e, cfg.hermes_gateway_url, cfg.hermes_gateway_secret)
        except Exception:
            log.exception('hermes dispatch failed from=%s', e.from_)


def main() -> None:
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
