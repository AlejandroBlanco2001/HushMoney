from __future__ import annotations

import email
import email.header
import imaplib
import logging
from dataclasses import dataclass

from forwarder.config import ImapConfig


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Email:
    from_: str
    subject: str
    body: str


def fetch_unread(cfg: ImapConfig) -> list[Email]:
    with imaplib.IMAP4_SSL(cfg.host, cfg.port) as conn:
        conn.login(cfg.username, cfg.password)
        conn.select(cfg.mailbox)

        results: list[Email] = []
        for sender in cfg.bank_senders:
            results.extend(_fetch_from_sender(conn, sender))

        return results


def _fetch_from_sender(conn: imaplib.IMAP4_SSL, sender: str) -> list[Email]:
    _, data = conn.search(None, 'UNSEEN', f'FROM "{sender}"')
    seq_nums: list[bytes] = data[0].split()
    if not seq_nums:
        return []

    results: list[Email] = []
    for seq in seq_nums:
        _, raw = conn.fetch(seq, '(RFC822)')
        if not raw or raw[0] is None:
            continue

        raw_bytes = raw[0][1] if isinstance(raw[0], tuple) else None
        if not isinstance(raw_bytes, bytes):
            continue

        msg = email.message_from_bytes(raw_bytes)
        body = _extract_plain_text(msg)
        if not body:
            log.warning('skipping email with no plain-text body')
            continue

        results.append(
            Email(
                from_=_resolve_original_sender(msg),
                subject=_decode_header(msg.get('Subject', '')),
                body=body.strip(),
            )
        )

        # Mark seen before returning — no retry queue by design; dropped messages are
        # preferable to re-processing and double-counting a transaction.
        conn.store(seq, '+FLAGS', '\\Seen')

    return results


def _resolve_original_sender(msg: email.message.Message) -> str:
    # Standard forwarding headers set by Outlook, Gmail, and most MTAs.
    # Fall back to the envelope From if none are present (direct send, no forwarding).
    for header in ('X-Original-From', 'X-Forwarded-From', 'Resent-From'):
        value = msg.get(header, '')
        if value:
            resolved = _decode_header(value)
            log.info('sender resolved via forwarding header')
            return resolved
    fallback = _decode_header(msg.get('From', ''))
    log.info('sender resolved via From header')
    return fallback


def _extract_plain_text(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == 'text/plain':
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    return payload.decode(part.get_content_charset() or 'utf-8', errors='replace')
    else:
        if msg.get_content_type() == 'text/plain':
            payload = msg.get_payload(decode=True)
            if isinstance(payload, bytes):
                return payload.decode(msg.get_content_charset() or 'utf-8', errors='replace')
    return ''


def parse_email_bytes(raw: bytes) -> Email | None:
    msg = email.message_from_bytes(raw)
    body = _extract_plain_text(msg)
    if not body:
        return None
    return Email(
        from_=_resolve_original_sender(msg),
        subject=_decode_header(msg.get('Subject', '')),
        body=body.strip(),
    )


def _decode_header(value: str) -> str:
    parts = []
    for fragment, charset in email.header.decode_header(value):
        if isinstance(fragment, bytes):
            parts.append(fragment.decode(charset or 'utf-8', errors='replace'))
        else:
            parts.append(fragment)
    return ''.join(parts)
