from __future__ import annotations

import re

from forwarder.sanitizer.banks import BankPatterns


_CURRENCY_AMOUNT = re.compile(r'\$\s?\d|\b(?:COP|USD)\s?\d', re.IGNORECASE)
_FINANCIAL_KEYWORDS = re.compile(
    r'\b(?:compra|compraste|pago|pagaste|transfer(?:iste|encia)|retir(?:aste|o)|'
    r'recib(?:iste|iste)|d[eé]bito|cr[eé]dito|abono|cargo|purchase|payment)\b',
    re.IGNORECASE,
)


def is_financial_notification(text: str, banks: tuple[BankPatterns, ...]) -> bool:
    """Return True if the text looks like a bank financial notification."""
    # Direct match on a known bank prefix or app name.
    for bank in banks:
        if bank.sms_prefix and bank.sms_prefix.match(text):
            return True
        for name in bank.app_names:
            if text.casefold().startswith(name.casefold() + ':'):
                return True
    # Heuristic: currency amount + financial keyword.
    return bool(_CURRENCY_AMOUNT.search(text) and _FINANCIAL_KEYWORDS.search(text))
