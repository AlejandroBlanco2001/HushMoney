from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal


type Channel = Literal['email', 'sms']
type TransactionType = Literal['debit', 'payment', 'transfer_out', 'transfer_in', 'cash']


@dataclass(frozen=True)
class CleanPayload:
    amount: float
    currency: str
    date: datetime
    transaction_type: TransactionType
    account_type: str
    channel: Channel
    merchant: str | None = None

    def to_json(self) -> dict[str, str | float]:
        payload: dict[str, str | float] = {
            'amount': self.amount,
            'currency': self.currency,
            'date': self.date.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'transaction_type': self.transaction_type,
            'account_type': self.account_type,
            'channel': self.channel,
        }
        if self.merchant is not None:
            payload['merchant'] = self.merchant
        return payload
