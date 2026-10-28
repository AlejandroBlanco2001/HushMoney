"""Regression tests for ADR-0007: candidate promotion wiring and feedback.

Guards two paths that were silently broken:
- A learned pattern that matches real traffic must record a use (track_use was
  never called, so candidates never auto-promoted).
- apply_feedback(verdict='wrong') must not raise (it called a non-existent
  LearnedPatternRow.source_is_community()).
"""

from __future__ import annotations

import pytest

from forwarder.learning.lifecycle import apply_feedback
from forwarder.learning.store import PatternStore
from forwarder.sanitizer import SanitizeStatus, sanitize
from forwarder.sanitizer import registry as registry_mod


# A learned pattern on the community `bancolombia` bank, with a message that no
# community pattern matches but this learned one does. The date matches the
# community bancolombia date regex so parsing reaches OK (and thus track_use).
_SAMPLE = 'Bancolombia: Abono por $50.000,00 recibido 24/10/2026 14:30'
_FINGERPRINT = 'testfp0001abcd'


@pytest.fixture
def store(tmp_path):
    """A real store attached to the global registry, restored afterward."""
    store = PatternStore(tmp_path / 'forwarder.db')
    reg = registry_mod.REGISTRY
    saved = (reg._store, reg._last_store_version, reg._last_reload, reg._snapshot)
    reg._store = store
    reg._last_store_version = ''
    reg._last_reload = 0.0
    try:
        yield store
    finally:
        (reg._store, reg._last_store_version, reg._last_reload, reg._snapshot) = saved


def _insert_candidate(store: PatternStore) -> int:
    return store.insert_pattern(
        bank_slug='bancolombia',
        channel='sms',
        template_key='bancolombia_abono_checking',
        transaction_type='transfer_in',
        account_type='checking',
        regex=r'Abono por \$(?P<amount>[\d.,]+) recibido',
        date_regex=None,
        synthetic_sample='',
        synthetic_expected='{}',
        fingerprint=_FINGERPRINT,
        proposal_id='test-proposal-1',
    )


def test_learned_pattern_match_records_use(store):
    pid = _insert_candidate(store)
    registry_mod.REGISTRY.reload_if_changed()

    result = sanitize(_SAMPLE, channel='sms')

    assert result.status == SanitizeStatus.MATCHED
    assert result.payload is not None
    assert result.payload.template_id == f'learned:{pid}'

    row = store.get_pattern_by_id(pid)
    assert row is not None
    assert row.uses == 1
    assert row.distinct_uses == 1


def test_apply_feedback_wrong_demotes_without_crashing(store):
    pid = _insert_candidate(store)
    store.upsert_fingerprint(_FINGERPRINT, 'bancolombia', 'sms', 'learned')

    apply_feedback(store, pid, 'wrong')  # previously raised AttributeError

    row = store.get_pattern_by_id(pid)
    assert row is not None
    assert row.status == 'rejected'
    assert row.corrections == 1
    fp = store.get_fingerprint(_FINGERPRINT)
    assert fp is not None
    assert fp['state'] == 'pending'


def test_apply_feedback_correct_counts_use(store):
    pid = _insert_candidate(store)

    apply_feedback(store, pid, 'correct')

    row = store.get_pattern_by_id(pid)
    assert row is not None
    assert row.uses == 1
    assert row.distinct_uses == 1
