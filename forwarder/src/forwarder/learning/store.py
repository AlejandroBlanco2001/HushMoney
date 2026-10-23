from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING

from forwarder.sanitizer.banks import BankPatterns, TransactionPattern


if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')


@dataclass(frozen=True)
class LearnedPatternRow:
    id: int
    bank_slug: str
    channel: str
    template_key: str
    transaction_type: str
    account_type: str
    regex: str
    date_regex: str | None
    synthetic_sample: str
    synthetic_expected: str
    fingerprint: str
    status: str
    uses: int
    distinct_uses: int
    last_use_hash: str | None
    corrections: int
    proposal_id: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class LearnedBankRow:
    slug: str
    country: str
    currency: str
    thousands_separator: str
    decimal_separator: str
    utc_offset_minutes: int
    sms_prefix: str | None
    email_senders: list[str]
    app_names: list[str]
    date_regex: str
    status: str


class PatternStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._local = threading.local()
        self._apply_schema()

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, 'conn'):
            conn = sqlite3.connect(str(self._path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA foreign_keys=ON')
            self._local.conn = conn
        return self._local.conn  # type: ignore[no-any-return]

    def _apply_schema(self) -> None:
        schema = files('forwarder.learning').joinpath('schema.sql').read_text()
        conn = self._conn()
        conn.executescript(schema)
        conn.commit()

    def data_version(self) -> str:
        row = (
            self._conn()
            .execute(
                "SELECT COALESCE(MAX(updated_at), '') || '|' || COUNT(*) FROM learned_patterns"
            )
            .fetchone()
        )
        return str(row[0]) if row else ''

    def get_active_patterns(self, bank_slug: str) -> list[LearnedPatternRow]:
        rows = (
            self._conn()
            .execute(
                'SELECT * FROM learned_patterns'
                " WHERE bank_slug = ? AND status IN ('active', 'candidate') ORDER BY id",
                (bank_slug,),
            )
            .fetchall()
        )
        return [_row_to_pattern(r) for r in rows]

    def get_all_active_patterns(self) -> list[LearnedPatternRow]:
        rows = (
            self._conn()
            .execute(
                "SELECT * FROM learned_patterns WHERE status IN ('active', 'candidate') ORDER BY id"
            )
            .fetchall()
        )
        return [_row_to_pattern(r) for r in rows]

    def get_learned_banks(self) -> list[LearnedBankRow]:
        rows = (
            self._conn().execute("SELECT * FROM learned_banks WHERE status = 'active'").fetchall()
        )
        return [_row_to_bank(r) for r in rows]

    def insert_pattern(
        self,
        bank_slug: str,
        channel: str,
        template_key: str,
        transaction_type: str,
        account_type: str,
        regex: str,
        date_regex: str | None,
        synthetic_sample: str,
        synthetic_expected: str,
        fingerprint: str,
        proposal_id: str,
    ) -> int:
        now = _now_iso()
        cur = self._conn().execute(
            """INSERT INTO learned_patterns
               (bank_slug, channel, template_key, transaction_type, account_type,
                regex, date_regex, synthetic_sample, synthetic_expected, fingerprint,
                status, proposal_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'candidate', ?, ?, ?)""",
            (
                bank_slug,
                channel,
                template_key,
                transaction_type,
                account_type,
                regex,
                date_regex,
                synthetic_sample,
                synthetic_expected,
                fingerprint,
                proposal_id,
                now,
                now,
            ),
        )
        self._conn().commit()
        return cur.lastrowid  # type: ignore[return-value]

    def insert_learned_bank(self, row: LearnedBankRow) -> None:
        now = _now_iso()
        self._conn().execute(
            """INSERT OR IGNORE INTO learned_banks
               (slug, country, currency, thousands_separator, decimal_separator,
                utc_offset_minutes, sms_prefix, email_senders, app_names,
                date_regex, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)""",
            (
                row.slug,
                row.country,
                row.currency,
                row.thousands_separator,
                row.decimal_separator,
                row.utc_offset_minutes,
                row.sms_prefix,
                json.dumps(row.email_senders),
                json.dumps(row.app_names),
                row.date_regex,
                now,
                now,
            ),
        )
        self._conn().commit()

    def update_pattern_status(self, pattern_id: int, status: str) -> None:
        self._conn().execute(
            'UPDATE learned_patterns SET status = ?, updated_at = ? WHERE id = ?',
            (status, _now_iso(), pattern_id),
        )
        self._conn().commit()

    def increment_uses(self, pattern_id: int, use_hash: str) -> None:
        conn = self._conn()
        row = conn.execute(
            'SELECT distinct_uses, last_use_hash FROM learned_patterns WHERE id = ?',
            (pattern_id,),
        ).fetchone()
        if row is None:
            return
        distinct = row['distinct_uses']
        if row['last_use_hash'] != use_hash:
            distinct += 1
        conn.execute(
            """UPDATE learned_patterns
               SET uses = uses + 1, distinct_uses = ?, last_use_hash = ?, updated_at = ?
               WHERE id = ?""",
            (distinct, use_hash, _now_iso(), pattern_id),
        )
        conn.commit()

    def increment_corrections(self, pattern_id: int) -> None:
        self._conn().execute(
            """UPDATE learned_patterns
               SET corrections = corrections + 1, status = 'rejected', updated_at = ?
               WHERE id = ?""",
            (_now_iso(), pattern_id),
        )
        self._conn().commit()

    def get_pattern_by_id(self, pattern_id: int) -> LearnedPatternRow | None:
        row = (
            self._conn()
            .execute('SELECT * FROM learned_patterns WHERE id = ?', (pattern_id,))
            .fetchone()
        )
        return _row_to_pattern(row) if row else None

    def get_fingerprint(self, fp: str) -> sqlite3.Row | None:
        return (
            self._conn()
            .execute(  # type: ignore[return-value]
                'SELECT * FROM fingerprints WHERE fingerprint = ?', (fp,)
            )
            .fetchone()
        )

    def upsert_fingerprint(
        self,
        fp: str,
        bank_slug: str | None,
        channel: str,
        state: str,
        last_forwarded: str | None = None,
    ) -> None:
        now = _now_iso()
        conn = self._conn()
        existing = conn.execute(
            'SELECT fingerprint FROM fingerprints WHERE fingerprint = ?', (fp,)
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE fingerprints
                   SET state = ?, hits = hits + 1, last_seen = ?,
                       last_forwarded = COALESCE(?, last_forwarded)
                   WHERE fingerprint = ?""",
                (state, now, last_forwarded, fp),
            )
        else:
            conn.execute(
                """INSERT INTO fingerprints
                   (fingerprint, bank_slug, channel, state,
                    hits, first_seen, last_seen, last_forwarded)
                   VALUES (?, ?, ?, ?, 1, ?, ?, ?)""",
                (fp, bank_slug, channel, state, now, now, last_forwarded),
            )
        conn.commit()

    def upsert_fingerprint_state(self, fp: str, state: str) -> None:
        now = _now_iso()
        conn = self._conn()
        conn.execute(
            'UPDATE fingerprints SET state = ?, last_seen = ? WHERE fingerprint = ?',
            (state, now, fp),
        )
        conn.commit()

    def log_proposal(self, proposal_id: str, kind: str, outcome: str, codes: list[str]) -> None:
        self._conn().execute(
            'INSERT OR IGNORE INTO proposals'
            ' (id, kind, outcome, codes, received_at) VALUES (?, ?, ?, ?, ?)',
            (proposal_id, kind, outcome, json.dumps(codes), _now_iso()),
        )
        self._conn().commit()

    def candidates_today(self, bank_slug: str) -> int:
        today = _now_iso()[:10]
        row = (
            self._conn()
            .execute(
                'SELECT COUNT(*) FROM learned_patterns'
                " WHERE bank_slug = ? AND status = 'candidate' AND created_at >= ?",
                (bank_slug, today + 'T00:00:00Z'),
            )
            .fetchone()
        )
        return int(row[0]) if row else 0

    def load_active_banks(self, community: tuple[BankPatterns, ...]) -> tuple[BankPatterns, ...]:
        community_slugs = {b.name for b in community}
        learned_bank_rows = self.get_learned_banks()
        all_patterns = self.get_all_active_patterns()

        patterns_by_bank: dict[str, list[LearnedPatternRow]] = {}
        for p in all_patterns:
            patterns_by_bank.setdefault(p.bank_slug, []).append(p)

        result: list[BankPatterns] = []

        # Merge learned patterns into community banks
        for bank in community:
            extra = patterns_by_bank.get(bank.name, [])
            if not extra:
                continue
            learned_txns = _patterns_to_transactions(extra, bank.name)
            merged = BankPatterns(
                name=bank.name,
                country=bank.country,
                currency=bank.currency,
                thousands_separator=bank.thousands_separator,
                decimal_separator=bank.decimal_separator,
                email_senders=bank.email_senders,
                sms_prefix=bank.sms_prefix,
                date=bank.date,
                transactions=bank.transactions + tuple(learned_txns),
                local_timezone=bank.local_timezone,
                app_names=bank.app_names,
            )
            result.append(merged)

        # Add fully learned banks (not in community)
        for bank_row in learned_bank_rows:
            if bank_row.slug in community_slugs:
                continue
            extra = patterns_by_bank.get(bank_row.slug, [])
            bank = _build_bank_from_rows(bank_row, extra)
            if bank:
                result.append(bank)

        return tuple(result)


def _build_bank_from_rows(
    row: LearnedBankRow, patterns: list[LearnedPatternRow]
) -> BankPatterns | None:
    from datetime import timedelta
    from datetime import timezone as tz

    try:
        local_tz = tz(timedelta(minutes=row.utc_offset_minutes))
        sms_prefix = re.compile(row.sms_prefix, re.IGNORECASE) if row.sms_prefix else None
        date_pattern = re.compile(row.date_regex)
        transactions = _patterns_to_transactions(patterns, row.slug)
        return BankPatterns(
            name=row.slug,
            country=row.country,
            currency=row.currency,
            thousands_separator=row.thousands_separator,
            decimal_separator=row.decimal_separator,
            email_senders=frozenset(row.email_senders),
            sms_prefix=sms_prefix,
            date=date_pattern,
            transactions=tuple(transactions),
            local_timezone=local_tz,
            app_names=frozenset(row.app_names),
        )
    except Exception:
        log.warning('failed to build bank from row %s', row.slug)
        return None


def _patterns_to_transactions(
    rows: list[LearnedPatternRow], bank_slug: str
) -> list[TransactionPattern]:
    result: list[TransactionPattern] = []
    for row in rows:
        try:
            import re as _re

            pattern = _re.compile(row.regex)
            date_re = _re.compile(row.date_regex) if row.date_regex else None
            result.append(
                TransactionPattern(
                    transaction_type=row.transaction_type,  # type: ignore[arg-type]
                    pattern=pattern,
                    account_type=row.account_type,
                    template_id=f'learned:{row.id}',
                    source='learned',
                    status=row.status,  # type: ignore[arg-type]
                    pattern_id=row.id,
                    channel=row.channel,  # type: ignore[arg-type]
                    date_regex=date_re,
                )
            )
        except Exception:
            log.warning('skipping corrupt learned pattern id=%s bank=%s', row.id, bank_slug)
    return result


def _row_to_pattern(row: sqlite3.Row) -> LearnedPatternRow:
    return LearnedPatternRow(
        id=row['id'],
        bank_slug=row['bank_slug'],
        channel=row['channel'],
        template_key=row['template_key'],
        transaction_type=row['transaction_type'],
        account_type=row['account_type'],
        regex=row['regex'],
        date_regex=row['date_regex'],
        synthetic_sample=row['synthetic_sample'],
        synthetic_expected=row['synthetic_expected'],
        fingerprint=row['fingerprint'],
        status=row['status'],
        uses=row['uses'],
        distinct_uses=row['distinct_uses'],
        last_use_hash=row['last_use_hash'],
        corrections=row['corrections'],
        proposal_id=row['proposal_id'],
        created_at=row['created_at'],
        updated_at=row['updated_at'],
    )


def _row_to_bank(row: sqlite3.Row) -> LearnedBankRow:
    return LearnedBankRow(
        slug=row['slug'],
        country=row['country'],
        currency=row['currency'],
        thousands_separator=row['thousands_separator'],
        decimal_separator=row['decimal_separator'],
        utc_offset_minutes=row['utc_offset_minutes'],
        sms_prefix=row['sms_prefix'],
        email_senders=json.loads(row['email_senders']),
        app_names=json.loads(row['app_names']),
        date_regex=row['date_regex'],
        status=row['status'],
    )
