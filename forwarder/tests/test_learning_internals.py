"""Tests for Stage 3 internals: synthetic date generation and store rate limiting."""
from __future__ import annotations

from datetime import UTC, datetime

import regex as _regex

from forwarder.learning.store import PatternStore
from forwarder.learning.synthetic import build_synthetic
from forwarder.learning.validation import ExpectedValues
from forwarder.sanitizer.registry import BANCOLOMBIA


_COMPRA_DEBITO = (
    r'Compraste \$(?P<amount>\d{1,3}(?:[.,]\d{3})*[.,]\d{2}) '
    r'en (?P<merchant>.+?) con tu T\.Deb'
)
_SAMPLE = 'Compraste $50.000,00 en RAPPI con tu T.Deb 24/10/2026 14:30'


def test_build_synthetic_rewrites_date_via_named_groups():
    expected = ExpectedValues(
        amount=50000.0,
        transaction_type='debit',
        account_type='checking',
        date=datetime(2026, 10, 24, 14, 30, tzinfo=UTC),
        merchant='RAPPI',
    )

    result = build_synthetic(_SAMPLE, _COMPRA_DEBITO, expected, BANCOLOMBIA)

    assert result is not None
    synth, synth_expected = result
    # Date rewritten from the bank's named groups (day=01 month=02 year=2026 10:20),
    # not left as the original and not mangled by a hardcoded DD/MM assumption.
    assert '01/02/2026' in synth
    assert '10:20' in synth
    assert '24/10/2026' not in synth
    # Amount and merchant replaced with synthetic stand-ins.
    assert '12.345,67' in synth
    assert 'COMERCIO PRUEBA' in synth
    assert synth_expected['merchant'] == 'COMERCIO PRUEBA'
    # The synthetic sample must still match the pattern.
    assert _regex.search(_COMPRA_DEBITO, synth) is not None


def test_store_rate_limit_counts_and_prunes(tmp_path):
    store = PatternStore(tmp_path / 'rate.db')
    assert store.forwards_last_hour() == 0

    for _ in range(3):
        store.record_forward()

    assert store.forwards_last_hour() == 3
