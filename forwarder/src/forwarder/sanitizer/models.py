from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal


type Channel = Literal['email', 'sms']
type TransactionType = Literal[
    'debit', 'payment', 'transfer_out', 'transfer_in', 'cash', 'credit', 'top_up'
]


@dataclass(frozen=True)
class CleanPayload:
    amount: float
    currency: str
    date: datetime
    transaction_type: TransactionType
    account_type: str
    channel: Channel
    merchant: str | None = None
    bank: str = 'unknown'
    template_id: str | None = None
    pattern_status: Literal['active', 'candidate'] = 'active'

    def to_json(self) -> dict[str, str | float]:
        payload: dict[str, str | float] = {
            'amount': self.amount,
            'currency': self.currency,
            'date': self.date.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'transaction_type': self.transaction_type,
            'account_type': self.account_type,
            'channel': self.channel,
            'bank': self.bank,
        }
        if self.merchant is not None:
            payload['merchant'] = self.merchant
        if self.template_id is not None and self.template_id.startswith('learned:'):
            payload['template_id'] = self.template_id
        if self.pattern_status == 'candidate':
            payload['pattern_status'] = self.pattern_status
        return payload
