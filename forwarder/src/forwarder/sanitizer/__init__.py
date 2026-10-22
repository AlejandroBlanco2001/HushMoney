from __future__ import annotations

import dataclasses
import re

from forwarder.sanitizer import parser
from forwarder.sanitizer.models import Channel, CleanPayload
from forwarder.sanitizer.redaction import REDACTED, redact
from forwarder.sanitizer.selector import BankSelector


__all__ = ['CleanPayload', 'sanitize', 'sanitize_push']

_BANK_SELECTOR = BankSelector()
_SUSPICIOUS_MERCHANT = re.compile(r'\d{4,}|@|https?:', re.IGNORECASE)


def sanitize_push(
    app_name: str, body: str, channel: Channel
) -> tuple[CleanPayload | None, bool]:
    """Try to parse a push notification given its app name and message body.

    Returns (payload, bank_found). bank_found=False means no bank matched the
    app name; bank_found=True means a bank was found but the message may not
    have matched any transaction pattern.
    """
    bank = _BANK_SELECTOR.select_bank_by_app(app_name)
    if bank is None:
        return None, False
    clean_body = redact(body)
    payload = parser.parse(clean_body, channel, bank)
    if payload is None or payload.merchant is None:
        return payload, True
    return dataclasses.replace(payload, merchant=_normalize_merchant(payload.merchant)), True


def sanitize(text: str, channel: Channel, *, sender: str | None = None) -> CleanPayload | None:
    clean_text = redact(text)
    bank = _BANK_SELECTOR.select_bank(clean_text, sender)
    if bank is None:
        return None
    payload = parser.parse(clean_text, channel, bank)
    if payload is None or payload.merchant is None:
        return payload
    return dataclasses.replace(payload, merchant=_normalize_merchant(payload.merchant))


def _normalize_merchant(raw: str) -> str | None:
    merchant = ' '.join(raw.split()).upper()
    # Merchant is the only free-text field that leaves the forwarder; if it still carries
    # anything that looks sensitive, drop it rather than ship it.
    if not merchant or REDACTED in merchant or _SUSPICIOUS_MERCHANT.search(merchant):
        return None
    return merchant
