from __future__ import annotations

import dataclasses
import re

from forwarder.sanitizer import parser
from forwarder.sanitizer.models import Channel, CleanPayload
from forwarder.sanitizer.redaction import REDACTED, redact
from forwarder.sanitizer.selector import BankSelector


__all__ = ['CleanPayload', 'sanitize']

_BANK_SELECTOR = BankSelector()
_SUSPICIOUS_MERCHANT = re.compile(r'\d{4,}|@|https?:', re.IGNORECASE)


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
