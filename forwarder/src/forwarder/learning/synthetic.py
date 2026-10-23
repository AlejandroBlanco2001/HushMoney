from __future__ import annotations

import re

import regex as _regex

from forwarder.sanitizer.banks import BankPatterns


_SYNTHETIC_AMOUNT = 12345.67
_SYNTHETIC_MERCHANT = 'COMERCIO PRUEBA'
_SYNTHETIC_DATE_REPLACEMENT = ('01', '02', '2026', '10', '20', '00')


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

        # Replace date components in the sample
        date_match = re.search(bank.date.pattern, synth)
        if date_match:
            old_date = date_match.group(0)
            day, month, year, hour, minute, _second = _SYNTHETIC_DATE_REPLACEMENT
            new_date = old_date
            new_date = re.sub(r'\b\d{4}\b', year, old_date, count=1)
            new_date = re.sub(r'\b\d{2}/\d{2}', f'{day}/{month}', new_date, count=1)
            new_date = re.sub(r'\b\d{2}:\d{2}', f'{hour}:{minute}', new_date, count=1)
            synth = synth.replace(old_date, new_date, 1)

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
