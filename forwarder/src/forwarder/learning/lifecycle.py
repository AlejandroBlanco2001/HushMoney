from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime, timedelta

from forwarder.learning.store import PatternStore


log = logging.getLogger(__name__)

PROMOTE_AFTER_DISTINCT_USES = 3
PROMOTE_MIN_AGE_HOURS = 24
RETIRE_AFTER_UNUSED_DAYS = 180


def track_use(store: PatternStore, pattern_id: int, amount: float, merchant: str | None) -> None:
    use_hash = hashlib.sha256(f'{amount}|{merchant or ""}'.encode()).hexdigest()[:12]
    store.increment_uses(pattern_id, use_hash)
    _maybe_promote(store, pattern_id)


def _maybe_promote(store: PatternStore, pattern_id: int) -> None:
    row = store.get_pattern_by_id(pattern_id)
    if row is None or row.status != 'candidate':
        return
    age = datetime.now(UTC) - datetime.fromisoformat(row.created_at.replace('Z', '+00:00'))
    if (
        row.distinct_uses >= PROMOTE_AFTER_DISTINCT_USES
        and row.corrections == 0
        and age >= timedelta(hours=PROMOTE_MIN_AGE_HOURS)
    ):
        store.update_pattern_status(pattern_id, 'active')
        log.info('pattern %d promoted to active', pattern_id)


def apply_feedback(store: PatternStore, pattern_id: int, verdict: str) -> None:
    row = store.get_pattern_by_id(pattern_id)
    if row is None:
        log.warning('feedback: pattern %d not found', pattern_id)
        return
    # Only learned patterns live in the store; community patterns ship in YAML and
    # have no row here, so there is nothing to guard against demoting.
    if verdict == 'wrong':
        store.increment_corrections(pattern_id)
        # Re-open the fingerprint so the next match triggers learning again
        if row.fingerprint:
            store.upsert_fingerprint_state(row.fingerprint, 'pending')
        log.info('pattern %d rejected by user feedback', pattern_id)
    elif verdict == 'correct' and row.status == 'candidate':
        use_hash = hashlib.sha256(b'user_confirmed').hexdigest()[:12]
        store.increment_uses(pattern_id, use_hash)
        _maybe_promote(store, pattern_id)
