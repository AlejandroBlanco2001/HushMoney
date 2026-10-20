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
