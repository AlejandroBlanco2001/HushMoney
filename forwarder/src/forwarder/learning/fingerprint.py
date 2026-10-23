from __future__ import annotations

import hashlib
import re


def fingerprint(redacted_text: str, bank_slug: str | None, channel: str) -> str:
    """Compute a short fingerprint for an unmatched message template.

    Merchants are not masked because their position in the text is unknown,
    so two purchases at different merchants may fingerprint differently. The
    second purchase will either hit 'duplicate_template' in validation or
    match the new candidate once it exists.
    """
    t = redacted_text.casefold()
    t = re.sub(r'\[redacted\]', '<r>', t)
    t = re.sub(r'\$?\s?\d[\d.,:/]*', '<n>', t)
    t = re.sub(r'\s+', ' ', t).strip()
    key = f'{bank_slug or "?"}|{channel}|{t}'
    return hashlib.sha256(key.encode()).hexdigest()[:16]
