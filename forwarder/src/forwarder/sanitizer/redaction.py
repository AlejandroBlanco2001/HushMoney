from __future__ import annotations

import re


REDACTED = '[REDACTED]'

# Order matters: specific phrases first, so the catch-all digit rule never sees half a token.
_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r'https?://\S+', re.IGNORECASE), REDACTED),
    # Bre-B llave: cédula, phone, email or alphanumeric alias, always a single token.
    # Stripped unconditionally because a cédula and a phone number look identical.
    (re.compile(r'(la llave)\s+\S+', re.IGNORECASE), rf'\1 {REDACTED}'),
    (re.compile(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+'), REDACTED),
    (re.compile(r'\*\d+'), f'*{REDACTED}'),
    (re.compile(r'(producto)\s+\d+', re.IGNORECASE), rf'\1 {REDACTED}'),
    (
        re.compile(r'\b(otp|c[oó]digo|clave)\b(\D{0,20}?)\d{4,8}\b', re.IGNORECASE),
        rf'\1\2{REDACTED}',
    ),
    # Phones, cédulas, OTPs and account numbers without a label. COP amounts always carry
    # thousand separators, so a bare run of 6+ digits is never an amount.
    (re.compile(r'\b\d{6,}\b'), REDACTED),
]


def redact(text: str) -> str:
    for pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    return text
