from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

import regex as _regex

from forwarder.sanitizer.banks import BankPatterns
from forwarder.sanitizer.registry import RegistrySnapshot


MAX_REGEX_LEN = 400
MIN_LITERAL_CHARS = 12
MIN_LITERAL_RATIO = 0.35

_VALID_NAMED_GROUPS = frozenset({'amount', 'merchant'})
_VALID_DATE_GROUPS = frozenset({'day', 'month', 'year', 'hour', 'minute', 'second'})


@dataclass(frozen=True)
class ExpectedValues:
    amount: float
    transaction_type: str
    account_type: str
    date: datetime
    merchant: str | None


@dataclass(frozen=True)
class Rejection:
    code: str
    detail: str


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    rejections: tuple[Rejection, ...]
    synthetic_sample: str | None = None
    synthetic_expected: dict[str, object] | None = None


def validate(
    regex: str,
    date_regex: str | None,
    sample: str,
    expected: ExpectedValues,
    bank: BankPatterns,
    snapshot: RegistrySnapshot,
    bank_slug: str,
    channel: str,
    template_key: str,
) -> ValidationResult:
    from forwarder.sanitizer.redaction import redact

    rejections: list[Rejection] = []

    # ── Gate 1: Static regex checks ───────────────────────────────────────────
    try:
        compiled = _regex.compile(regex)
    except Exception as exc:
        return ValidationResult(
            ok=False,
            rejections=(Rejection('regex_invalid', str(exc)),),
        )

    if len(regex) > MAX_REGEX_LEN:
        rejections.append(Rejection('regex_too_long', f'len={len(regex)}'))

    named_groups = set(compiled.groupindex.keys())
    if 'amount' not in named_groups:
        rejections.append(Rejection('missing_amount_group', 'no ?P<amount> group'))

    unknown_groups = named_groups - _VALID_NAMED_GROUPS
    if unknown_groups:
        rejections.append(Rejection('unknown_group', ', '.join(sorted(unknown_groups))))

    merchant_in_regex = 'merchant' in named_groups
    merchant_expected = expected.merchant is not None
    if merchant_in_regex != merchant_expected:
        rejections.append(
            Rejection(
                'merchant_group_mismatch',
                f'regex has merchant={merchant_in_regex},'
                f' expected has merchant={merchant_expected}',
            )
        )

    literal_chars = _count_literal_chars(regex)
    if literal_chars < MIN_LITERAL_CHARS or (
        len(regex) > 0 and literal_chars / len(regex) < MIN_LITERAL_RATIO
    ):
        rejections.append(
            Rejection(
                'too_generic',
                f'literal_chars={literal_chars} ratio={literal_chars / max(len(regex), 1):.2f}',
            )
        )

    if _has_unbounded_outside_merchant(regex):
        rejections.append(Rejection('unbounded_wildcard', 'found .* or .+ outside merchant group'))

    if date_regex is not None:
        try:
            date_compiled = _regex.compile(date_regex)
            date_groups = set(date_compiled.groupindex.keys())
            bad_date_groups = date_groups - _VALID_DATE_GROUPS
            required_date_groups = {'day', 'month', 'year', 'hour', 'minute'}
            missing_date_groups = required_date_groups - date_groups
            if bad_date_groups:
                rejections.append(
                    Rejection('unknown_group', 'date_regex: ' + ', '.join(sorted(bad_date_groups)))
                )
            if missing_date_groups:
                rejections.append(
                    Rejection(
                        'missing_amount_group',
                        'date_regex missing: ' + ', '.join(sorted(missing_date_groups)),
                    )
                )
        except Exception as exc:
            rejections.append(Rejection('regex_invalid', f'date_regex: {exc}'))

    if rejections:
        return ValidationResult(ok=False, rejections=tuple(rejections))

    # ── Gate 2: Reproduces confirmed values on sample ─────────────────────────
    if redact(sample) != sample:
        rejections.append(Rejection('sample_not_redacted', 'sample contains unredacted content'))
        return ValidationResult(ok=False, rejections=tuple(rejections))

    match = _regex.search(regex, sample, timeout=0.1)
    if match is None:
        rejections.append(Rejection('no_match_on_sample', 'regex did not match the sample'))
        return ValidationResult(ok=False, rejections=tuple(rejections))

    from decimal import Decimal, InvalidOperation

    raw_amount = match.group('amount')
    tsep, dsep = bank.thousands_separator, bank.decimal_separator
    try:
        amount_val = float(raw_amount.replace(tsep, '').replace(dsep, '.'))
    except ValueError:
        rejections.append(Rejection('amount_mismatch', f'could not parse amount {raw_amount!r}'))
        return ValidationResult(ok=False, rejections=tuple(rejections))

    try:
        q = Decimal('0.01')
        if Decimal(str(amount_val)).quantize(q) != Decimal(str(expected.amount)).quantize(q):
            rejections.append(
                Rejection('amount_mismatch', f'got {amount_val} expected {expected.amount}')
            )
    except InvalidOperation:
        rejections.append(Rejection('amount_mismatch', 'decimal comparison failed'))

    if merchant_in_regex:
        raw_merchant = match.group('merchant')
        normalized = ' '.join(raw_merchant.split()).upper() if raw_merchant else None
        if normalized != expected.merchant:
            rejections.append(Rejection('merchant_mismatch', 'merchant did not match'))

    # Date check
    date_pat = _regex.compile(date_regex) if date_regex else None
    date_src = str(date_pat.pattern if date_pat else bank.date.pattern)
    date_match = re.search(date_src, sample)
    if date_match is None:
        rejections.append(Rejection('date_failed', 'date regex did not match sample'))
    else:
        from forwarder.sanitizer import parser as _parser

        parsed_date = _parser.parse_date(sample, bank, bank.date)
        if parsed_date is not None and abs((parsed_date - expected.date).total_seconds()) > 60:
            rejections.append(Rejection('date_mismatch', 'parsed date differs from expected'))

    # ── Gate 4: Collision ─────────────────────────────────────────────────────
    for b in snapshot.banks:
        if b.name != bank_slug:
            continue
        for txn in b.transactions:
            if txn.template_id and txn.template_id != f'{bank_slug}.{template_key}':  # noqa: SIM102
                if _regex.search(txn.pattern.pattern, sample, timeout=0.05):
                    rejections.append(
                        Rejection('collides_with_existing', f'also matched by {txn.template_id}')
                    )
                    break

    if rejections:
        return ValidationResult(ok=False, rejections=tuple(rejections))

    # Build synthetic sample
    from forwarder.learning.synthetic import build_synthetic

    synth_result = build_synthetic(sample, regex, expected, bank)
    if synth_result is None:
        return ValidationResult(
            ok=False,
            rejections=(Rejection('synthetic_failed', 'could not build synthetic sample'),),
        )

    return ValidationResult(
        ok=True,
        rejections=(),
        synthetic_sample=synth_result[0],
        synthetic_expected=synth_result[1],
    )


def _count_literal_chars(pattern: str) -> int:
    # Strip character classes, named groups, special sequences, quantifiers,
    # anchors, and alternations; count what remains as literal chars.
    s = re.sub(r'\[.*?\]', '', pattern)  # char classes
    s = re.sub(r'\(\?P<\w+>', '', s)  # named group openers
    s = re.sub(r'\\[dDwWsSbBAZ]', '', s)  # escape sequences
    s = re.sub(r'[(){|^$*+?]', '', s)  # metacharacters
    s = re.sub(r'\\\\.', '', s)  # escaped literals (backslash pairs)
    s = re.sub(r'\\[.,!@#%&\-]', ' ', s)  # common escaped punct
    return len(re.sub(r'\s', '', s))


def _has_unbounded_outside_merchant(pattern: str) -> bool:
    # Check for .* or .+ that is NOT inside a (?P<merchant> group.
    # Simple approach: strip the merchant group content and then look.
    stripped = re.sub(r'\(\?P<merchant>.+?\)', '(merchant)', pattern, flags=re.DOTALL)
    return bool(re.search(r'\.[\*+]', stripped))
