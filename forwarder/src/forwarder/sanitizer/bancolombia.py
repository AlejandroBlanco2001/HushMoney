from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone

from forwarder.sanitizer.models import Channel, CleanPayload, TransactionType


COLOMBIA_TZ = timezone(timedelta(hours=-5))

# SMS apps have been seen dropping the leading "B".
_BANK_PREFIX = re.compile(r'\s*B?ancolombia:')
_AMOUNT = r'\$(?P<amount>\d{1,3}(?:\.\d{3})*,\d{2})'
_DATE = re.compile(
    r'(?P<day>\d{2})/(?P<month>\d{2})/(?P<year>\d{4}|\d{2})\s+(?:a las\s+)?'
    r'(?P<hour>\d{2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?',
)

# Credit card (T.Cred) and ATM (Retiraste) templates are left out until real samples exist;
# unmatched messages return None instead of being guessed at.
_TEMPLATES: list[tuple[TransactionType, re.Pattern[str]]] = [
    ('debit', re.compile(rf'Compraste {_AMOUNT} en (?P<merchant>.+?) con tu T\.Deb')),
    ('payment', re.compile(rf'Pagaste {_AMOUNT} a (?P<merchant>.+?) desde tu producto')),
    ('transfer_out', re.compile(rf'Transferiste {_AMOUNT} desde tu cuenta')),
    ('transfer_in', re.compile(rf'recibiste una transferencia de .+? por {_AMOUNT}')),
]


def parse(text: str, channel: Channel) -> CleanPayload | None:
    if not _BANK_PREFIX.match(text):
        return None

    date = _parse_date(text)
    if date is None:
        return None

    for transaction_type, template in _TEMPLATES:
        match = template.search(text)
        if match is None:
            continue
        return CleanPayload(
            amount=_parse_amount(match['amount']),
            currency='COP',
            date=date,
            transaction_type=transaction_type,
            account_type='checking',
            channel=channel,
            merchant=match.groupdict().get('merchant'),
        )
    return None


def _parse_amount(raw: str) -> float:
    return float(raw.replace('.', '').replace(',', '.'))


def _parse_date(text: str) -> datetime | None:
    match = _DATE.search(text)
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
            int(match['second'] or 0),
            tzinfo=COLOMBIA_TZ,
        )
    except ValueError:
        return None
    return local.astimezone(UTC)
