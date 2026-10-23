from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

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
    def __init__(
        self,
        store: PatternStore,
        hermes_webhook_url: str,
        webhook_secret: str,
    ) -> None:
        self._store = store
        self._hermes_url = hermes_webhook_url
        self._webhook_secret = webhook_secret

    def handle(
        self,
        redacted_text: str,
        bank_slug: str | None,
        channel: str,
        status: SanitizeStatus,
        update_id: int = 0,
        message_id: int = 0,
        date: int = 0,
        chat_id: int = 0,
    ) -> None:
        fp = compute_fingerprint(redacted_text, bank_slug, channel)
        existing = self._store.get_fingerprint(fp)

        if existing is not None:
            state = str(existing['state'])
            if state == 'ignored':
                self._store.upsert_fingerprint(fp, bank_slug, channel, 'ignored')
                log.info('unmatched fingerprint=%s state=ignored', fp)
                return
            if state == 'pending':
                last_fwd = existing['last_forwarded']
                if last_fwd:
                    age = datetime.now(UTC) - datetime.fromisoformat(
                        last_fwd.replace('Z', '+00:00')
                    )
                    if age < timedelta(days=LEARNING_RETRY_AFTER_DAYS):
                        self._store.upsert_fingerprint(fp, bank_slug, channel, 'pending')
                        log.info('unmatched fingerprint=%s state=pending (cooling), forwarding as repeat', fp)
                        self._forward(
                            redacted_text, bank_slug, channel, status, fp,
                            update_id, message_id, date, chat_id, repeat=True,
                        )
                        return
            if state == 'learned':
                log.warning('unmatched fingerprint=%s state=learned (possible regression)', fp)

        if not _check_rate_limit():
            log.warning('unmatched rate limit reached, fingerprint=%s dropped', fp)
            self._store.upsert_fingerprint(fp, bank_slug, channel, 'pending')
            return

        from datetime import datetime as _dt

        now_iso = _dt.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')
        self._store.upsert_fingerprint(fp, bank_slug, channel, 'pending', last_forwarded=now_iso)
        self._forward(
            redacted_text, bank_slug, channel, status, fp, update_id, message_id, date, chat_id
        )

    def _forward(
        self,
        redacted_text: str,
        bank_slug: str | None,
        channel: str,
        status: SanitizeStatus,
        fp: str,
        update_id: int,
        message_id: int,
        date: int,
        chat_id: int,
        repeat: bool = False,
    ) -> None:
        # Strip any lines that could spoof the [bank_learning] header.
        safe_lines = [
            line
            for line in redacted_text.splitlines()
            if not line.startswith('[bank_learning]') and line != '---'
        ]
        safe_text = '\n'.join(safe_lines)

        reason = 'pending_repeat' if repeat else _status_to_reason(status)
        header = (
            f'[bank_learning]\n'
            f'reason: {reason}\n'
            f'channel: {channel}\n'
            f'bank: {bank_slug or "unknown"}\n'
            f'fingerprint: {fp}\n'
            f'---\n'
            f'{safe_text}'
        )

        body = {
            'update_id': update_id,
            'message': {
                'message_id': message_id,
                'date': date,
                'chat': {'id': chat_id, 'type': 'private'},
                'from': {'id': chat_id, 'is_bot': False, 'first_name': 'User'},
                'text': header,
            },
        }
        self._post(body)
        log.info('unmatched forwarded fingerprint=%s bank=%s channel=%s', fp, bank_slug, channel)

    def _post(self, body: Mapping[str, object]) -> None:
        import httpx

        text = (body.get('message') or {}).get('text', '')  # type: ignore[union-attr]
        if not text:
            return
        try:
            resp = httpx.post(self._hermes_url, json={'text': text}, timeout=10)
            resp.raise_for_status()
        except Exception:
            log.warning('unmatched: failed to forward to hermes')

    async def handle_async(
        self,
        redacted_text: str,
        bank_slug: str | None,
        channel: str,
        status: SanitizeStatus,
        update_id: int,
        message_id: int,
        date: int,
        chat_id: int,
        client: object,
    ) -> None:
        fp = compute_fingerprint(redacted_text, bank_slug, channel)
        existing = self._store.get_fingerprint(fp)

        if existing is not None:
            state = str(existing['state'])
            if state == 'ignored':
                self._store.upsert_fingerprint(fp, bank_slug, channel, 'ignored')
                log.info('unmatched fingerprint=%s state=ignored', fp)
                return
            if state == 'pending':
                last_fwd = existing['last_forwarded']
                if last_fwd:
                    age = datetime.now(UTC) - datetime.fromisoformat(
                        last_fwd.replace('Z', '+00:00')
                    )
                    if age < timedelta(days=LEARNING_RETRY_AFTER_DAYS):
                        self._store.upsert_fingerprint(fp, bank_slug, channel, 'pending')
                        log.info('unmatched fingerprint=%s state=pending (cooling), forwarding as repeat', fp)
                        await self._forward_async(
                            redacted_text, bank_slug, channel, status, fp,
                            update_id, message_id, date, chat_id, client, repeat=True,
                        )
                        return
            if state == 'learned':
                log.warning('unmatched fingerprint=%s state=learned (possible regression)', fp)

        if not _check_rate_limit():
            log.warning('unmatched rate limit reached, fingerprint=%s dropped', fp)
            self._store.upsert_fingerprint(fp, bank_slug, channel, 'pending')
            return

        from datetime import datetime as _dt

        now_iso = _dt.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')
        self._store.upsert_fingerprint(fp, bank_slug, channel, 'pending', last_forwarded=now_iso)
        await self._forward_async(
            redacted_text,
            bank_slug,
            channel,
            status,
            fp,
            update_id,
            message_id,
            date,
            chat_id,
            client,
        )

    async def _forward_async(
        self,
        redacted_text: str,
        bank_slug: str | None,
        channel: str,
        status: SanitizeStatus,
        fp: str,
        update_id: int,
        message_id: int,
        date: int,
        chat_id: int,
        client: object,
        repeat: bool = False,
    ) -> None:
        import httpx

        safe_lines = [
            line
            for line in redacted_text.splitlines()
            if not line.startswith('[bank_learning]') and line != '---'
        ]
        safe_text = '\n'.join(safe_lines)

        reason = 'pending_repeat' if repeat else _status_to_reason(status)
        header = (
            f'[bank_learning]\n'
            f'reason: {reason}\n'
            f'channel: {channel}\n'
            f'bank: {bank_slug or "unknown"}\n'
            f'fingerprint: {fp}\n'
            f'---\n'
            f'{safe_text}'
        )

        body = {
            'update_id': update_id,
            'message': {
                'message_id': message_id,
                'date': date,
                'chat': {'id': chat_id, 'type': 'private'},
                'from': {'id': chat_id, 'is_bot': False, 'first_name': 'User'},
                'text': header,
            },
        }
        try:
            assert isinstance(client, httpx.AsyncClient)
            resp = await client.post(self._hermes_url, json={'text': header})
            resp.raise_for_status()
            log.info('unmatched forwarded fingerprint=%s bank=%s', fp, bank_slug)
        except Exception:
            log.warning('unmatched: failed to forward to hermes')
