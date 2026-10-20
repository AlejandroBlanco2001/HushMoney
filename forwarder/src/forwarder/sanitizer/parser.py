from __future__ import annotations

from datetime import UTC, datetime

from forwarder.sanitizer.banks import BankPatterns
from forwarder.sanitizer.models import Channel, CleanPayload


def parse(text: str, channel: Channel, bank: BankPatterns) -> CleanPayload | None:
    date = _parse_date(text, bank)
    if date is None:
        return None
    for transaction in bank.transactions:
        match = transaction.pattern.search(text)
        if match is None:
            continue
        amount = match['amount'].replace(bank.thousands_separator, '')
        amount = amount.replace(bank.decimal_separator, '.')
        return CleanPayload(
            amount=float(amount),
            currency=bank.currency,
            date=date,
            transaction_type=transaction.transaction_type,
            account_type=transaction.account_type,
            channel=channel,
            merchant=match.groupdict().get('merchant'),
        )
    return None


def _parse_date(text: str, bank: BankPatterns) -> datetime | None:
    match = bank.date.search(text)
    if match is None:
        return None
    year = int(match['year'])
    if year < 100:
        year += 2000
    try:
        local = datetime(
            year,
            int(match['month']),
            int(match['day']),
            int(match['hour']),
            int(match['minute']),
            int(match.groupdict().get('second') or 0),
            tzinfo=bank.local_timezone,
        )
    except ValueError:
        return None
    return local.astimezone(UTC)
