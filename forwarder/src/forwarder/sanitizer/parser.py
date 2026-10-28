from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import cast

from forwarder.sanitizer.banks import BankPatterns, TransactionPattern
from forwarder.sanitizer.models import Channel, CleanPayload


log = logging.getLogger(__name__)

LEARNED_REGEX_TIMEOUT_S = 0.05


class ParseStatus(StrEnum):
    OK = 'ok'
    NO_TEMPLATE = 'no_template'
    DATE_FAILED = 'date_failed'
    INVALID_AMOUNT = 'invalid_amount'


@dataclass(frozen=True)
class ParseResult:
    status: ParseStatus
    payload: CleanPayload | None = None
    template: TransactionPattern | None = None


def parse_amount(raw: str, bank: BankPatterns) -> float | None:
    """Parse a captured amount string to a float, or None if unparseable.

    Auto-detects separators from the string, falling back to the bank's declared
    separators. Shared by the live parser and by learned-pattern validation so the
    two never diverge on the same input.
    """
    value = _auto_parse_amount(raw)
    if value is None:
        # Fall back to bank's declared separators.
        tsep, dsep = bank.thousands_separator, bank.decimal_separator
        try:
            value = float(raw.replace(tsep, '').replace(dsep, '.'))
        except ValueError:
            return None
    if value <= 0 or value >= 1e10:
        return None
    return value


def _auto_parse_amount(raw: str) -> float | None:
    """Detect separators from the string itself, ignoring bank config.

    When both . and , are present the one that appears last is the decimal
    separator — true for any well-formed monetary string regardless of locale.
    When only one is present, 1-2 trailing digits → decimal; 3 → thousands.
    """
    has_dot = '.' in raw
    has_comma = ',' in raw
    try:
        if has_dot and has_comma:
            if raw.rfind('.') > raw.rfind(','):
                return float(raw.replace(',', ''))  # 1,000.00 → 1000.00
            else:
                return float(raw.replace('.', '').replace(',', '.'))  # 1.000,00 → 1000.00
        elif has_dot:
            if re.search(r'\.\d{1,2}$', raw):
                return float(raw)  # 1000.50
            else:
                return float(raw.replace('.', ''))  # 1.000 → 1000
        elif has_comma:
            if re.search(r',\d{1,2}$', raw):
                return float(raw.replace(',', '.'))  # 1000,50 → 1000.50
            else:
                return float(raw.replace(',', ''))  # 1,000 → 1000
        else:
            return float(raw)
    except ValueError:
        return None


def _search(pattern: TransactionPattern, text: str) -> re.Match[str] | None:
    if pattern.source == 'learned':
        try:
            import regex as _regex

            m = _regex.search(pattern.pattern.pattern, text, timeout=LEARNED_REGEX_TIMEOUT_S)
            return cast(re.Match[str] | None, m)
        except Exception:
            log.warning('learned pattern %s timed out or errored', pattern.template_id)
            return None
    return pattern.pattern.search(text)


def parse(text: str, channel: Channel, bank: BankPatterns) -> ParseResult:
    for transaction in bank.transactions:
        if transaction.channel not in ('any', channel):
            continue
        match = _search(transaction, text)
        if match is None:
            continue

        raw_amount = match['amount']
        amount = parse_amount(raw_amount, bank)
        if amount is None:
            return ParseResult(status=ParseStatus.INVALID_AMOUNT, template=transaction)

        date_pattern = transaction.date_regex or bank.date
        date = parse_date(text, bank, date_pattern)
        if date is None:
            return ParseResult(status=ParseStatus.DATE_FAILED, template=transaction)

        merchant_raw: str | None = match.groupdict().get('merchant')
        payload = CleanPayload(
            amount=float(amount),
            currency=bank.currency,
            date=date,
            transaction_type=transaction.transaction_type,
            account_type=transaction.account_type,
            channel=channel,
            merchant=merchant_raw,
            bank=bank.name,
            template_id=transaction.template_id or None,
            pattern_status=transaction.status,
        )
        return ParseResult(status=ParseStatus.OK, payload=payload, template=transaction)

    return ParseResult(status=ParseStatus.NO_TEMPLATE)


def parse_date(text: str, bank: BankPatterns, date_pattern: object) -> datetime | None:
    if hasattr(date_pattern, 'pattern'):
        pat = str(cast(re.Pattern[str], date_pattern).pattern)
    else:
        pat = str(date_pattern)
    m = re.search(pat, text)
    if m is None:
        return None
    year = int(m['year'])
    if year < 100:
        year += 2000
    try:
        local = datetime(
            year,
            int(m['month']),
            int(m['day']),
            int(m['hour']),
            int(m['minute']),
            int(m.groupdict().get('second') or 0),
            tzinfo=bank.local_timezone,
        )
    except ValueError:
        return None
    return local.astimezone(UTC)
