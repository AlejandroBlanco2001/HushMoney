from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta

import httpx

from forwarder.learning.fingerprint import fingerprint as compute_fingerprint
from forwarder.learning.store import PatternStore
from forwarder.sanitizer import SanitizeStatus


log = logging.getLogger(__name__)

LEARNING_RETRY_AFTER_DAYS = 7
LEARNING_MAX_PER_HOUR = 10

_forwarded_this_hour: list[float] = []


def _check_rate_limit() -> bool:
    now = time.monotonic()
    cutoff = now - 3600
    while _forwarded_this_hour and _forwarded_this_hour[0] < cutoff:
        _forwarded_this_hour.pop(0)
    if len(_forwarded_this_hour) >= LEARNING_MAX_PER_HOUR:
        return False
    _forwarded_this_hour.append(now)
    return True


def _status_to_reason(status: SanitizeStatus) -> str:
    return {
        SanitizeStatus.BANK_UNKNOWN: 'bank_unknown',
        SanitizeStatus.NO_TEMPLATE: 'no_template',
        SanitizeStatus.DATE_FAILED: 'date_failed',
        SanitizeStatus.INVALID_AMOUNT: 'invalid_amount',
    }.get(status, 'no_template')


class UnmatchedHandler:
    """Route unparseable notifications to the bank_learning skill.

    Dedupes by fingerprint: ignored fingerprints are dropped, pending ones still
    inside the cooling window are re-forwarded as repeats, and anything else is
    forwarded once (subject to an hourly rate limit). The sync `handle` serves the
    IMAP poller; the async `handle_async` serves the Telegram webhook. Both share
    the same decision logic (`_classify`) and envelope (`_build_envelope`) — only
    the HTTP call differs.
    """

    def __init__(
        self,
        store: PatternStore,
        hermes_webhook_url: str,
        webhook_secret: str,
    ) -> None:
        self._store = store
        self._hermes_url = hermes_webhook_url
        self._webhook_secret = webhook_secret

    def _classify(
        self, redacted_text: str, bank_slug: str | None, channel: str
    ) -> tuple[str, bool, bool]:
        """Decide what to do with an unmatched message, recording fingerprint state.

        Returns (fingerprint, should_forward, is_repeat).
        """
        fp = compute_fingerprint(redacted_text, bank_slug, channel)
        existing = self._store.get_fingerprint(fp)

        if existing is not None:
            state = str(existing['state'])
            if state == 'ignored':
                self._store.upsert_fingerprint(fp, bank_slug, channel, 'ignored')
                log.info('unmatched fingerprint=%s state=ignored', fp)
                return fp, False, False
            if state == 'pending':
                last_fwd = existing['last_forwarded']
                if last_fwd:
                    age = datetime.now(UTC) - datetime.fromisoformat(
                        last_fwd.replace('Z', '+00:00')
                    )
                    if age < timedelta(days=LEARNING_RETRY_AFTER_DAYS):
                        self._store.upsert_fingerprint(fp, bank_slug, channel, 'pending')
                        log.info(
                            'unmatched fingerprint=%s state=pending (cooling), '
                            'forwarding as repeat',
                            fp,
                        )
                        return fp, True, True
            if state == 'learned':
                log.warning('unmatched fingerprint=%s state=learned (possible regression)', fp)

        if not _check_rate_limit():
            log.warning('unmatched rate limit reached, fingerprint=%s dropped', fp)
            self._store.upsert_fingerprint(fp, bank_slug, channel, 'pending')
            return fp, False, False

        now_iso = datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')
        self._store.upsert_fingerprint(fp, bank_slug, channel, 'pending', last_forwarded=now_iso)
        return fp, True, False

    def _build_envelope(
        self,
        redacted_text: str,
        bank_slug: str | None,
        channel: str,
        status: SanitizeStatus,
        fp: str,
        repeat: bool,
    ) -> str:
        # Strip any lines that could spoof the [bank_learning] header.
        safe_lines = [
            line
            for line in redacted_text.splitlines()
            if not line.startswith('[bank_learning]') and line != '---'
        ]
        safe_text = '\n'.join(safe_lines)
        reason = 'pending_repeat' if repeat else _status_to_reason(status)
        return (
            f'[bank_learning]\n'
            f'reason: {reason}\n'
            f'channel: {channel}\n'
            f'bank: {bank_slug or "unknown"}\n'
            f'fingerprint: {fp}\n'
            f'---\n'
            f'{safe_text}'
        )

    def handle(
        self,
        redacted_text: str,
        bank_slug: str | None,
        channel: str,
        status: SanitizeStatus,
    ) -> None:
        fp, should_forward, repeat = self._classify(redacted_text, bank_slug, channel)
        if not should_forward:
            return
        header = self._build_envelope(redacted_text, bank_slug, channel, status, fp, repeat)
        try:
            resp = httpx.post(self._hermes_url, json={'text': header}, timeout=10)
            resp.raise_for_status()
            log.info(
                'unmatched forwarded fingerprint=%s bank=%s channel=%s', fp, bank_slug, channel
            )
        except Exception:
            log.warning('unmatched: failed to forward to hermes')

    async def handle_async(
        self,
        *,
        redacted_text: str,
        bank_slug: str | None,
        channel: str,
        status: SanitizeStatus,
        client: httpx.AsyncClient,
    ) -> None:
        fp, should_forward, repeat = self._classify(redacted_text, bank_slug, channel)
        if not should_forward:
            return
        header = self._build_envelope(redacted_text, bank_slug, channel, status, fp, repeat)
        try:
            resp = await client.post(self._hermes_url, json={'text': header})
            resp.raise_for_status()
            log.info(
                'unmatched forwarded fingerprint=%s bank=%s channel=%s', fp, bank_slug, channel
            )
        except Exception:
            log.warning('unmatched: failed to forward to hermes')
