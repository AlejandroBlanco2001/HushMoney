from __future__ import annotations

from email.utils import parseaddr

from forwarder.sanitizer.banks import BankPatterns
from forwarder.sanitizer.registry import RegistrySnapshot


class BankSelector:
    def __init__(self, snapshot: RegistrySnapshot) -> None:
        self._banks = snapshot.banks
        self._by_sender = snapshot.by_sender

    def select_bank(self, text: str, sender: str | None = None) -> BankPatterns | None:
        if sender is not None:
            _, address = parseaddr(sender)
            return self._by_sender.get(address.casefold())
        return next(
            (bank for bank in self._banks if bank.sms_prefix and bank.sms_prefix.match(text)),
            None,
        )

    def select_bank_by_app(self, app_name: str) -> BankPatterns | None:
        name_lower = app_name.casefold()
        return next(
            (
                bank
                for bank in self._banks
                if bank.name.casefold() == name_lower
                or any(n.casefold() == name_lower for n in bank.app_names)
            ),
            None,
        )
