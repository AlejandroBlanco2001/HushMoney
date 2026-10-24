from __future__ import annotations

import dataclasses
import logging
import re
from dataclasses import dataclass
from enum import StrEnum

from forwarder.sanitizer import parser
from forwarder.sanitizer.models import Channel, CleanPayload
from forwarder.sanitizer.parser import ParseStatus
from forwarder.sanitizer.redaction import REDACTED, redact
from forwarder.sanitizer.registry import REGISTRY
from forwarder.sanitizer.selector import BankSelector


__all__ = ['CleanPayload', 'SanitizeResult', 'SanitizeStatus', 'sanitize', 'sanitize_push']

log = logging.getLogger(__name__)

_SUSPICIOUS_MERCHANT = re.compile(r'\d{4,}|@|https?:', re.IGNORECASE)


class SanitizeStatus(StrEnum):
    MATCHED = 'matched'
    BANK_UNKNOWN = 'bank_unknown'
    NO_TEMPLATE = 'no_template'
    DATE_FAILED = 'date_failed'
    INVALID_AMOUNT = 'invalid_amount'


@dataclass(frozen=True)
class SanitizeResult:
    status: SanitizeStatus
    redacted_text: str
    bank_slug: str | None
    payload: CleanPayload | None = None


_PARSE_TO_SANITIZE: dict[ParseStatus, SanitizeStatus] = {
    ParseStatus.NO_TEMPLATE: SanitizeStatus.NO_TEMPLATE,
    ParseStatus.DATE_FAILED: SanitizeStatus.DATE_FAILED,
    ParseStatus.INVALID_AMOUNT: SanitizeStatus.INVALID_AMOUNT,
}


def sanitize_push(app_name: str, body: str, channel: Channel) -> tuple[CleanPayload | None, bool]:
    """Try to parse a push notification given its app name and message body.

    Returns (payload, bank_found). bank_found=False means no bank matched the
    app name; bank_found=True means a bank was found but the message may not
    have matched any transaction pattern.
    """
    REGISTRY.reload_if_changed()
    snap = REGISTRY.snapshot()
    bank = BankSelector(snap).select_bank_by_app(app_name)
    if bank is None:
        return None, False
    clean_body = redact(body)
    result = parser.parse(clean_body, channel, bank)
    if result.status != ParseStatus.OK or result.payload is None:
        return None, True
    payload = result.payload
    if payload.merchant is not None:
        payload = dataclasses.replace(payload, merchant=_normalize_merchant(payload.merchant))
    _record_learned_use(result.template, payload)
    return payload, True


def sanitize(text: str, channel: Channel, *, sender: str | None = None) -> SanitizeResult:
    REGISTRY.reload_if_changed()
    snap = REGISTRY.snapshot()
    clean_text = redact(text)
    bank = BankSelector(snap).select_bank(clean_text, sender)
    if bank is None:
        return SanitizeResult(
            status=SanitizeStatus.BANK_UNKNOWN,
            redacted_text=clean_text,
            bank_slug=None,
        )
    result = parser.parse(clean_text, channel, bank)
    if result.status != ParseStatus.OK or result.payload is None:
        return SanitizeResult(
            status=_PARSE_TO_SANITIZE.get(result.status, SanitizeStatus.NO_TEMPLATE),
            redacted_text=clean_text,
            bank_slug=bank.name,
        )
    payload = result.payload
    if payload.merchant is not None:
        payload = dataclasses.replace(payload, merchant=_normalize_merchant(payload.merchant))
    _record_learned_use(result.template, payload)
    return SanitizeResult(
        status=SanitizeStatus.MATCHED,
        redacted_text=clean_text,
        bank_slug=bank.name,
        payload=payload,
    )


def _record_learned_use(template: object, payload: CleanPayload) -> None:
    """Count a successful match of a learned pattern toward candidate promotion.

    Community patterns are already active and are not tracked. No-op when the
    registry has no store attached (e.g. community-only test contexts).
    """
    from forwarder.sanitizer.banks import TransactionPattern

    if not isinstance(template, TransactionPattern):
        return
    if template.source != 'learned' or template.pattern_id is None:
        return
    store = REGISTRY.store
    if store is None:
        return
    from forwarder.learning.lifecycle import track_use

    try:
        track_use(store, template.pattern_id, payload.amount, payload.merchant)
    except Exception:  # usage tracking must never break parsing
        log.warning('failed to record use of learned pattern %s', template.pattern_id)


def _normalize_merchant(raw: str) -> str | None:
    merchant = ' '.join(raw.split()).upper()
    if not merchant or REDACTED in merchant or _SUSPICIOUS_MERCHANT.search(merchant):
        return None
    return merchant
