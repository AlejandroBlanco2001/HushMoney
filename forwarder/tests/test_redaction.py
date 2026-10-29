from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from forwarder.sanitizer import sanitize
from forwarder.sanitizer.redaction import REDACTED, redact


@pytest.mark.parametrize(
    'text',
    [
        'Verification code: 0000',
        'Your security code is 000000',
        'One-time password: 00000000',
        'PIN: 0000',
        'account ending in 1234',
        'Account number: 1234',
        'card ending 1234',
        'card number: XXXX-XXXX-XXXX-1234',
        'product 1234',
        'payment key @SYNTHETIC',
        'Bre-B key @SYNTHETIC',
        'Tu codigo es 0000',
        'la llave @SYNTHETIC',
    ],
)
def test_spanish_and_english_sensitive_labels_are_redacted(text):
    result = redact(text)
    assert REDACTED in result
    for secret in ('0000', '1234', '@SYNTHETIC'):
        assert secret not in result


@given(code=st.text(alphabet='0123456789', min_size=4, max_size=8))
def test_english_code_inside_merchant_never_leaves_sanitizer(code):
    text = (
        f'Bancolombia: Compraste $32.500,00 en EXITO verification code: {code} '
        'con tu T.Deb *1234, el 15/09/2026 a las 20:35.'
    )
    result = sanitize(text, 'sms')
    assert result.payload is not None
    assert result.payload.merchant is None


# ── Property-based invariants ───────────────────────────────────────────────


@given(text=st.text(max_size=500))
def test_redact_never_raises_on_arbitrary_text(text):
    redact(text)


@given(text=st.text(max_size=500))
def test_redact_is_idempotent(text):
    once = redact(text)
    assert redact(once) == once


@given(
    local=st.text(
        alphabet=st.characters(whitelist_categories=('Ll', 'Lu', 'Nd')), min_size=1, max_size=16
    ),
    domain=st.text(alphabet='abcdefghijklmnopqrstuvwxyz', min_size=1, max_size=10),
    tld=st.sampled_from(['com', 'org', 'co', 'net', 'com.co']),
)
def test_email_addresses_are_always_redacted(local, domain, tld):
    email = f'{local}@{domain}.{tld}'
    result = redact(f'contact {email} for details')
    assert email not in result
    assert REDACTED in result


@given(digits=st.text(alphabet='0123456789', min_size=1, max_size=8))
def test_masked_card_token_is_redacted(digits):
    assert digits not in redact(f'con tu tarjeta *{digits}')


@given(digits=st.text(alphabet='0123456789', min_size=6, max_size=24))
def test_long_unlabelled_digit_run_is_redacted(digits):
    result = redact(f'ref {digits} end')
    assert digits not in result
    assert REDACTED in result
