from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import tzinfo
from typing import Literal

from forwarder.sanitizer.models import TransactionType


@dataclass(frozen=True)
class TransactionPattern:
    transaction_type: TransactionType
    pattern: re.Pattern[str]
    account_type: str = 'checking'
    template_id: str = ''
    source: Literal['community', 'learned'] = 'community'
    status: Literal['active', 'candidate'] = 'active'
    pattern_id: int | None = None
    channel: Literal['sms', 'email', 'any'] = 'any'
    date_regex: re.Pattern[str] | None = None


@dataclass(frozen=True)
class BankPatterns:
    name: str
    email_senders: frozenset[str]
    sms_prefix: re.Pattern[str] | None
    date: re.Pattern[str]
    transactions: tuple[TransactionPattern, ...]
    local_timezone: tzinfo
    country: str = 'CO'
    currency: str = 'COP'
    thousands_separator: str = '.'
    decimal_separator: str = ','
    app_names: frozenset[str] = field(default_factory=frozenset)  # pyright: ignore[reportUnknownVariableType]
