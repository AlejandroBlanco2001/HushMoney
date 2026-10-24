from __future__ import annotations

import re

import regex as _regex

from forwarder.sanitizer.banks import BankPatterns


_SYNTHETIC_AMOUNT = 12345.67
_SYNTHETIC_MERCHANT = 'COMERCIO PRUEBA'
_SYNTHETIC_DATE_PARTS = {
    'day': '01',
    'month': '02',
    'year': '2026',
    'hour': '10',
    'minute': '20',
    'second': '00',
}


def _synthesize_date(match: re.Match[str]) -> str:
    """Rebuild a matched date string with synthetic values, per named group.

    Locale-agnostic: it splices each named group's captured span (day/month/year/
    hour/minute/second) rather than assuming a DD/MM HH:MM layout.
    """
    text = match.group(0)
    base = match.start()
    spans: list[tuple[int, int, str]] = []
    for name, value in _SYNTHETIC_DATE_PARTS.items():
        try:
            start, end = match.span(name)
        except IndexError:
            continue  # group not present in this bank's date regex
        if start < 0:
            continue
        if name == 'year' and (end - start) == 2:
            value = value[-2:]  # two-digit year regex expects two digits
        spans.append((start - base, end - base, value))
    for start, end, value in sorted(spans, key=lambda s: s[0], reverse=True):
        text = text[:start] + value + text[end:]
    return text


def _format_amount(amount: float, bank: BankPatterns) -> str:
    tsep = bank.thousands_separator
    dsep = bank.decimal_separator
    # Format with two decimal places.
    integer_part = int(amount)
    decimal_part = round((amount - integer_part) * 100)
    int_str = f'{integer_part:,}'.replace(',', tsep)
    return f'${int_str}{dsep}{decimal_part:02d}'


def build_synthetic(
    sample: str,
    regex_str: str,
    expected: object,
    bank: BankPatterns,
) -> tuple[str, dict[str, object]] | None:
    try:
        match = _regex.search(regex_str, sample, timeout=0.1)
        if match is None:
            return None

        synth = sample

        # Replace merchant
        if 'merchant' in match.groupdict() and match.group('merchant'):
            synth = synth.replace(match.group('merchant'), _SYNTHETIC_MERCHANT, 1)

        # Replace amount
        raw_amount = match.group('amount')
        synth_amount_str = _format_amount(_SYNTHETIC_AMOUNT, bank).lstrip('$')
        synth = synth.replace(raw_amount, synth_amount_str, 1)

        # Replace date components in the sample, using the bank's own named groups.
        date_match = re.search(bank.date.pattern, synth)
        if date_match:
            old_date = date_match.group(0)
            synth = synth.replace(old_date, _synthesize_date(date_match), 1)

        # Verify the synthetic sample matches the regex
        synth_match = _regex.search(regex_str, synth, timeout=0.1)
        if synth_match is None:
            return None

        # Build expected JSON for the synthetic sample
        synth_expected: dict[str, object] = {
            'amount': _SYNTHETIC_AMOUNT,
            'merchant': (
                _SYNTHETIC_MERCHANT
                if 'merchant' in synth_match.groupdict() and synth_match.group('merchant')
                else None
            ),
        }

        return synth, synth_expected
    except Exception:
        return None
