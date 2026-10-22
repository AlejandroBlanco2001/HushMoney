from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta, timezone, tzinfo

from forwarder.sanitizer.models import TransactionType


@dataclass(frozen=True)
class TransactionPattern:
    transaction_type: TransactionType
    pattern: re.Pattern[str]
    account_type: str = 'checking'


@dataclass(frozen=True)
class BankPatterns:
    name: str
    email_senders: frozenset[str]
    prefix: re.Pattern[str]
    date: re.Pattern[str]
    transactions: tuple[TransactionPattern, ...]
    local_timezone: tzinfo
    currency: str = 'COP'
    thousands_separator: str = '.'
    decimal_separator: str = ','
    app_names: frozenset[str] = frozenset()


# Accepts both Colombian ($6.930,00) and US ($1,000.00) number formats.
_AMOUNT = r'\$(?P<amount>\d{1,3}(?:[.,]\d{3})*[.,]\d{2})'
BANCOLOMBIA = BankPatterns(
    name='bancolombia',
    email_senders=frozenset(
        {
            'alertasynotificaciones@ayn.notificacionesbancolombia.com',
            'alertasynotificaciones@an.notificacionesbancolombia.com',
        }
    ),
    # SMS apps have been seen dropping the leading "B".
    prefix=re.compile(r'\s*B?ancolombia:', re.IGNORECASE),
    date=re.compile(
        r'(?P<day>\d{2})/(?P<month>\d{2})/(?P<year>\d{4}|\d{2})\s+(?:a las\s+)?'
        r'(?P<hour>\d{2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?',
    ),
    transactions=(
        TransactionPattern(
            'debit',
            re.compile(
                rf'Compraste {_AMOUNT} en (?P<merchant>.+?) con tu T\.Deb',
            ),
        ),
        TransactionPattern(
            'debit',
            re.compile(
                rf'Compraste {_AMOUNT} en (?P<merchant>.+?) con tu T\.Cred',
            ),
            account_type='credit',
        ),
        TransactionPattern('cash', re.compile(rf'Retiraste {_AMOUNT} de la cuenta')),
        TransactionPattern(
            'payment',
            re.compile(
                rf'Pagaste {_AMOUNT} a (?P<merchant>.+?) desde tu producto',
            ),
        ),
        TransactionPattern('transfer_out', re.compile(rf'Transferiste {_AMOUNT} desde tu cuenta')),
        TransactionPattern(
            'transfer_in',
            re.compile(
                rf'recibiste una transferencia de .+? por {_AMOUNT}',
            ),
        ),
    ),
    local_timezone=timezone(timedelta(hours=-5)),
)

BANKS = (BANCOLOMBIA,)
