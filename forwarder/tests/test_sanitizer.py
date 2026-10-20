from __future__ import annotations

import email
import json
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from forwarder.imap import _extract_plain_text
from forwarder.sanitizer import sanitize


FIXTURES = Path(__file__).resolve().parents[2] / 'tests' / 'fixtures'
ALLOWED_KEYS = {
    'amount',
    'currency',
    'merchant',
    'date',
    'transaction_type',
    'account_type',
    'channel',
}


def _discover() -> list[Path]:
    return sorted([*FIXTURES.glob('emails/**/*.eml'), *FIXTURES.glob('sms/**/*.txt')])


def _read_body(path: Path) -> str:
    if path.suffix == '.eml':
        return _extract_plain_text(email.message_from_bytes(path.read_bytes())).strip()
    return path.read_text(encoding='utf-8').strip()


@pytest.mark.parametrize(
    'raw_path',
    _discover(),
    ids=lambda p: str(p.relative_to(FIXTURES)),
)
def test_fixture_matches_expected(raw_path: Path):
    expected_path = raw_path.with_name(raw_path.stem + '.expected.json')
    assert expected_path.exists(), f'missing {expected_path.name}'

    channel = 'email' if raw_path.suffix == '.eml' else 'sms'
    payload = sanitize(_read_body(raw_path), channel=channel)

    assert payload is not None, 'no pattern matched'
    assert payload.to_json() == json.loads(expected_path.read_text(encoding='utf-8'))


def test_unknown_bank_is_not_matched():
    text = 'RappiPay: Compraste $47.350,00 en Rappi con tu T.Deb *1234, el 15/09/2026 a las 12:43.'
    assert sanitize(text, channel='sms') is None


def test_missing_leading_b_still_matches():
    text = (
        'ancolombia: Compraste $32.500,00 en UBER RIDES con tu T.Deb *1234, '
        'el 15/09/2026 a las 20:35.'
    )
    payload = sanitize(text, channel='sms')
    assert payload is not None
    assert payload.merchant == 'UBER RIDES'


digits = st.text(alphabet='0123456789', min_size=1)
cedulas = st.text(alphabet='0123456789', min_size=10, max_size=10)
phones = st.text(alphabet='0123456789', min_size=9, max_size=9).map(lambda d: f'3{d}')
emails = st.from_regex(r'[a-z][a-z0-9.]{2,10}@[a-z]{3,8}\.(com|co|net)', fullmatch=True)
aliases = st.from_regex(r'@?[A-Z][A-Z0-9]{5,12}', fullmatch=True)
llaves = st.one_of(cedulas, phones, emails, aliases)
otps = st.text(alphabet='0123456789', min_size=6, max_size=8)
accounts = st.text(alphabet='0123456789', min_size=4, max_size=11)


@given(llave=llaves, otp=otps, account=accounts)
def test_transfer_secrets_never_survive(llave: str, otp: str, account: str):
    text = (
        'Bancolombia: MARIA GARCIA, recibiste una transferencia de JUAN PEREZ por $185.000,00 '
        f'en tu cuenta *{account} conectada a la llave {llave} el 14/09/26 a las 01:40. '
        f'Tu codigo OTP es {otp}. Con llaves es de una y gratis. Dudas al 018000912345'
    )
    payload = sanitize(text, channel='sms')

    assert payload is not None
    serialized = json.dumps(payload.to_json())
    for secret in (llave, otp, 'MARIA', 'JUAN', '018000912345'):
        assert secret not in serialized
    assert payload.merchant is None


# A bare alphanumeric alias (no '@') is indistinguishable from a store name outside the
# "la llave" phrase, so only context-free secrets are injected into the merchant slot.
merchant_secrets = st.one_of(
    cedulas,
    phones,
    emails,
    otps,
    aliases.filter(lambda a: a.startswith('@')),
)


@given(secret=merchant_secrets, account=accounts)
def test_secret_inside_merchant_is_dropped(secret: str, account: str):
    text = (
        f'Bancolombia: Compraste $47.350,00 en TIENDA {secret} con tu T.Deb *{account}, '
        'el 15/09/2026 a las 12:43.'
    )
    payload = sanitize(text, channel='email')

    assert payload is not None
    assert payload.merchant is None or secret not in payload.merchant


@given(merchant=st.text(min_size=1, max_size=60))
def test_merchant_never_carries_digit_runs_or_addresses(merchant: str):
    text = (
        f'Bancolombia: Compraste $10.000,00 en {merchant} con tu T.Deb *1234, '
        'el 15/09/2026 a las 12:43.'
    )
    payload = sanitize(text, channel='email')

    if payload is not None and payload.merchant is not None:
        assert '@' not in payload.merchant
        assert not any(run.isdigit() and len(run) >= 4 for run in payload.merchant.split())


@given(text=st.text())
def test_arbitrary_input_never_raises_or_adds_fields(text: str):
    payload = sanitize(text, channel='sms')
    if payload is not None:
        assert set(payload.to_json()) <= ALLOWED_KEYS
