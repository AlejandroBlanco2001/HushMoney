from __future__ import annotations

import dataclasses
import re

from forwarder.sanitizer import bancolombia
from forwarder.sanitizer.models import Channel, CleanPayload
from forwarder.sanitizer.redaction import REDACTED, redact


__all__ = ['CleanPayload', 'sanitize']

_SUSPICIOUS_MERCHANT = re.compile(r'\d{4,}|@|https?:', re.IGNORECASE)


def sanitize(text: str, channel: Channel) -> CleanPayload | None:
    """Return a clean payload, or None when no known bank pattern matches."""
    payload = bancolombia.parse(redact(text), channel)
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
