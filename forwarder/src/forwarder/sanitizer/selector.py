from __future__ import annotations

from email.utils import parseaddr

from forwarder.sanitizer.banks import BANKS, BankPatterns


class BankSelector:
    def __init__(self, banks: tuple[BankPatterns, ...] = BANKS) -> None:
        self.banks = banks
        self.by_sender = {
            sender.casefold(): bank for bank in banks for sender in bank.email_senders
        }

    def select_bank(self, text: str, sender: str | None = None) -> BankPatterns | None:
        if sender is not None:
            # Sender routing is exact; an unknown sender must not fall back to body text.
            _, address = parseaddr(sender)
            return self.by_sender.get(address.casefold())
        return next((bank for bank in self.banks if bank.prefix.match(text)), None)

    def select_bank_by_app(self, app_name: str) -> BankPatterns | None:
        """Look up a bank by mobile push-notification app name (case-insensitive)."""
        name_lower = app_name.casefold()
        return next(
            (
                bank for bank in self.banks
                if bank.name.casefold() == name_lower
                or any(n.casefold() == name_lower for n in bank.app_names)
            ),
            None,
        )
