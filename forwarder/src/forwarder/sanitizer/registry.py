from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta, timezone
from importlib.resources import files
from typing import TYPE_CHECKING, cast

import yaml

from forwarder.sanitizer.banks import BankPatterns, TransactionPattern


if TYPE_CHECKING:
    from forwarder.learning.store import PatternStore


log = logging.getLogger(__name__)

REGISTRY_RELOAD_MIN_INTERVAL_S = 2.0

_VALID_TRANSACTION_TYPES: frozenset[str] = frozenset(
    ['debit', 'payment', 'transfer_out', 'transfer_in', 'cash', 'credit', 'top_up']
)


@dataclass(frozen=True)
class RegistrySnapshot:
    banks: tuple[BankPatterns, ...]
    by_sender: Mapping[str, BankPatterns]
    version: str


def _load_yaml_bank(data: dict[str, object]) -> BankPatterns:
    name = str(data['name'])
    country = str(data.get('country', 'CO'))
    currency = str(data.get('currency', 'COP'))
    thousands_sep = str(data.get('thousands_separator', '.'))
    decimal_sep = str(data.get('decimal_separator', ','))
    utc_offset = int(data['utc_offset_minutes'])  # type: ignore[arg-type]
    local_tz = timezone(timedelta(minutes=utc_offset))

    sms_prefix_str = data.get('sms_prefix')
    sms_prefix = re.compile(str(sms_prefix_str), re.IGNORECASE) if sms_prefix_str else None

    date_pattern = re.compile(str(data['date']))

    email_senders_raw = data.get('email_senders', [])
    _es_list = cast(list[object], email_senders_raw if isinstance(email_senders_raw, list) else [])
    email_senders: frozenset[str] = frozenset(str(s) for s in _es_list)

    app_names_raw = data.get('app_names', [])
    _an_list = cast(list[object], app_names_raw if isinstance(app_names_raw, list) else [])
    app_names: frozenset[str] = frozenset(str(a) for a in _an_list)

    fragments: dict[str, str] = {}
    raw_frags = cast(dict[object, object], data.get('amount_fragments') or {})
    for k, v in raw_frags.items():
        fragments[str(k)] = str(v)

    transactions_raw = data.get('transactions', [])
    transactions: list[TransactionPattern] = []
    for tx in cast(list[object], transactions_raw if isinstance(transactions_raw, list) else []):
        tx_data: dict[str, object] = dict(tx)  # type: ignore[arg-type]
        tx_id = str(tx_data['id'])
        tx_type = str(tx_data['transaction_type'])
        if tx_type not in _VALID_TRANSACTION_TYPES:
            raise ValueError(f'Unknown transaction_type {tx_type!r} in {name}/{tx_id}')
        regex_str = str(tx_data['regex'])
        for frag_key, frag_val in fragments.items():
            regex_str = regex_str.replace(f'{{{frag_key}}}', frag_val)
        pattern = re.compile(regex_str)
        account_type = str(tx_data.get('account_type', 'checking'))
        transactions.append(
            TransactionPattern(
                transaction_type=tx_type,  # type: ignore[arg-type]
                pattern=pattern,
                account_type=account_type,
                template_id=f'{name}.{tx_id}',
                source='community',
                status='active',
                channel='any',
            )
        )

    return BankPatterns(
        name=name,
        country=country,
        currency=currency,
        thousands_separator=thousands_sep,
        decimal_separator=decimal_sep,
        email_senders=email_senders,
        sms_prefix=sms_prefix,
        date=date_pattern,
        transactions=tuple(transactions),
        local_timezone=local_tz,
        app_names=app_names,
    )


def load_community_banks() -> tuple[BankPatterns, ...]:
    pkg = files('forwarder.sanitizer.patterns')
    banks: list[BankPatterns] = []
    for resource in pkg.iterdir():  # type: ignore[union-attr]
        if not resource.name.endswith('.yaml'):
            continue
        raw = resource.read_text(encoding='utf-8')
        data: object = yaml.safe_load(raw)
        if not isinstance(data, dict):
            raise ValueError(f'Invalid YAML in {resource.name}')
        banks.append(_load_yaml_bank(cast(dict[str, object], data)))
    return tuple(banks)


def _build_snapshot(
    community: tuple[BankPatterns, ...],
    learned: tuple[BankPatterns, ...],
    store_version: str,
) -> RegistrySnapshot:
    # `learned` already contains the merged form of any community bank it extends
    # (community transactions + learned ones), so a learned entry must *replace* the
    # base community entry of the same name — not sit alongside it. Otherwise SMS
    # selection, which scans this list in order, would pick the base copy first and
    # never see the learned patterns.
    by_name: dict[str, BankPatterns] = {bank.name: bank for bank in community}
    for bank in learned:
        by_name[bank.name] = bank
    all_banks = tuple(by_name.values())

    by_sender: dict[str, BankPatterns] = {}
    for bank in all_banks:
        for sender in bank.email_senders:
            by_sender[sender.casefold()] = bank
    content = store_version + '|' + ','.join(b.name for b in all_banks)
    version = hashlib.sha256(content.encode()).hexdigest()[:12]
    return RegistrySnapshot(banks=all_banks, by_sender=by_sender, version=version)


class PatternRegistry:
    def __init__(self, store: PatternStore | None = None) -> None:
        self._store = store
        self._community = load_community_banks()
        self._lock = threading.Lock()
        self._last_reload = 0.0
        self._last_store_version: str = ''
        self._snapshot = _build_snapshot(self._community, (), '')

    def snapshot(self) -> RegistrySnapshot:
        return self._snapshot

    @property
    def store(self) -> PatternStore | None:
        return self._store

    def reload_if_changed(self) -> None:
        now = time.monotonic()
        with self._lock:
            if now - self._last_reload < REGISTRY_RELOAD_MIN_INTERVAL_S:
                return
            self._last_reload = now

        if self._store is None:
            return

        try:
            current_version = self._store.data_version()
        except Exception:
            log.warning('registry: failed to read store version')
            return

        if current_version == self._last_store_version:
            return

        try:
            learned = self._store.load_active_banks(self._community)
        except Exception:
            log.warning('registry: failed to load learned patterns')
            return

        new_snapshot = _build_snapshot(self._community, learned, current_version)
        self._snapshot = new_snapshot
        self._last_store_version = current_version
        log.info('registry reloaded version=%s', new_snapshot.version)


# Module-level instance (no store; store is injected by __main__ after DB init).
# Tests and callers that only need community patterns can use this directly.
REGISTRY = PatternRegistry()


# Convenience alias for tests / backward compat
def _get_bancolombia() -> BankPatterns:
    snap = REGISTRY.snapshot()
    return next(b for b in snap.banks if b.name == 'bancolombia')


BANCOLOMBIA = _get_bancolombia()
