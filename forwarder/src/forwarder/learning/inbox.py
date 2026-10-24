from __future__ import annotations

import json
import logging
import shutil
import threading
import time
from pathlib import Path
from typing import cast

from forwarder.learning.store import LearnedBankRow, PatternStore
from forwarder.learning.validation import ExpectedValues, validate
from forwarder.sanitizer.banks import BankPatterns
from forwarder.sanitizer.registry import PatternRegistry


log = logging.getLogger(__name__)

INBOX_POLL_INTERVAL_S = 1.0
MAX_PROPOSAL_BYTES = 65_536
MAX_CANDIDATES_PER_BANK_PER_DAY = 5


class InboxWatcher:
    def __init__(self, inbox_dir: Path, store: PatternStore, registry: PatternRegistry) -> None:
        self._proposals = inbox_dir / 'proposals'
        self._results = inbox_dir / 'results'
        self._processing = inbox_dir / 'processing'
        self._registry_json = inbox_dir / 'registry.json'
        self._store = store
        self._registry = registry
        for d in (self._proposals, self._results, self._processing):
            d.mkdir(parents=True, exist_ok=True)

    def start(self) -> None:
        self._recover_processing()
        self._write_registry_json()
        t = threading.Thread(target=self._loop, daemon=True, name='inbox-watcher')
        t.start()
        log.info('inbox watcher started')

    def _recover_processing(self) -> None:
        for f in self._processing.glob('*.json'):
            dest = self._proposals / f.name
            shutil.move(str(f), dest)
            log.info('inbox: recovered %s', f.name)

    def _loop(self) -> None:
        while True:
            try:
                self._tick()
            except Exception:
                log.exception('inbox watcher error')
            time.sleep(INBOX_POLL_INTERVAL_S)

    def _tick(self) -> None:
        for proposal_file in sorted(self._proposals.glob('*.json')):
            if proposal_file.suffix == '.tmp':
                continue
            processing_file = self._processing / proposal_file.name
            proposal_file.rename(processing_file)
            try:
                self._handle(processing_file)
            except Exception:
                log.exception('inbox: failed to handle %s', processing_file.name)
            finally:
                if processing_file.exists():
                    processing_file.unlink()

    def _handle(self, path: Path) -> None:
        if path.stat().st_size > MAX_PROPOSAL_BYTES:
            self._write_result(path.stem, 'error', ['schema_invalid'], None, None)
            return

        try:
            data: object = json.loads(path.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._write_result(path.stem, 'error', ['schema_invalid'], None, None)
            return

        if not isinstance(data, dict):
            self._write_result(path.stem, 'error', ['schema_invalid'], None, None)
            return

        data_d = cast(dict[str, object], data)
        proposal_id = str(data_d.get('proposal_id', path.stem))
        kind = str(data_d.get('kind', ''))

        if kind == 'pattern':
            self._handle_pattern(proposal_id, data_d)
        elif kind == 'ignore':
            self._handle_ignore(proposal_id, data_d)
        elif kind == 'feedback':
            self._handle_feedback(proposal_id, data_d)
        else:
            self._store.log_proposal(proposal_id, kind, 'error', ['unknown_kind'])
            self._write_result(proposal_id, 'error', ['unknown_kind'], None, None)

        self._write_registry_json()

    def _handle_pattern(self, proposal_id: str, data: dict[str, object]) -> None:
        if not data.get('user_confirmed'):
            self._store.log_proposal(proposal_id, 'pattern', 'rejected', ['not_confirmed'])
            self._write_result(proposal_id, 'rejected', ['not_confirmed'], None, None)
            return

        bank_slug = str(data.get('bank_slug', ''))
        channel = str(data.get('channel', ''))
        template_key = str(data.get('template_key', ''))
        regex_str = str(data.get('regex', ''))
        date_regex_str = data.get('date_regex')
        date_regex = str(date_regex_str) if date_regex_str else None
        sample = str(data.get('sample', ''))
        fp = str(data.get('fingerprint', ''))

        raw_expected = data.get('expected', {})
        if not isinstance(raw_expected, dict):
            self._store.log_proposal(proposal_id, 'pattern', 'rejected', ['schema_invalid'])
            self._write_result(proposal_id, 'rejected', ['schema_invalid'], None, None)
            return

        expected_d = cast(dict[str, object], raw_expected)
        try:
            from datetime import datetime as _dt

            raw_date = str(expected_d.get('date', '')).replace('Z', '+00:00')
            expected_date = _dt.fromisoformat(raw_date)
            expected = ExpectedValues(
                amount=float(expected_d.get('amount', 0)),  # type: ignore[arg-type]
                transaction_type=str(expected_d.get('transaction_type', '')),
                account_type=str(expected_d.get('account_type', '')),
                date=expected_date,
                merchant=expected_d.get('merchant') or None,  # type: ignore[arg-type]
            )
        except (ValueError, TypeError, KeyError):
            self._store.log_proposal(proposal_id, 'pattern', 'rejected', ['schema_invalid'])
            self._write_result(proposal_id, 'rejected', ['schema_invalid'], None, None)
            return

        # Check per-day cap
        if self._store.candidates_today(bank_slug) >= MAX_CANDIDATES_PER_BANK_PER_DAY:
            self._store.log_proposal(proposal_id, 'pattern', 'rejected', ['rate_limited'])
            self._write_result(proposal_id, 'rejected', ['rate_limited'], None, None)
            return

        snap = self._registry.snapshot()
        bank = next((b for b in snap.banks if b.name == bank_slug), None)

        # Handle unknown bank
        bank_profile_data = data.get('bank_profile')
        if bank is None:
            if not bank_profile_data or not isinstance(bank_profile_data, dict):
                code = 'bank_profile_missing'
                self._store.log_proposal(proposal_id, 'pattern', 'rejected', [code])
                self._write_result(proposal_id, 'rejected', [code], None, None)
                return
            bank = _build_bank_from_profile(cast(dict[str, object], bank_profile_data))
            if bank is None:
                code = 'bank_profile_invalid'
                self._store.log_proposal(proposal_id, 'pattern', 'rejected', [code])
                self._write_result(proposal_id, 'rejected', [code], None, None)
                return
            bank_row = LearnedBankRow(
                slug=bank_slug,
                country=bank.country,
                currency=bank.currency,
                thousands_separator=bank.thousands_separator,
                decimal_separator=bank.decimal_separator,
                utc_offset_minutes=_tz_to_minutes(bank.local_timezone),
                sms_prefix=bank.sms_prefix.pattern if bank.sms_prefix else None,
                email_senders=list(bank.email_senders),
                app_names=list(bank.app_names),
                date_regex=bank.date.pattern,
                status='active',
            )
            self._store.insert_learned_bank(bank_row)

        result = validate(
            regex=regex_str,
            date_regex=date_regex,
            sample=sample,
            expected=expected,
            bank=bank,
            snapshot=snap,
            bank_slug=bank_slug,
            channel=channel,
            template_key=template_key,
        )

        if not result.ok:
            codes = [r.code for r in result.rejections]
            self._store.log_proposal(proposal_id, 'pattern', 'rejected', codes)
            self._write_result(
                proposal_id,
                'rejected',
                codes,
                None,
                None,
                rejections=[{'code': r.code, 'detail': r.detail} for r in result.rejections],
            )
            return

        pattern_id = self._store.insert_pattern(
            bank_slug=bank_slug,
            channel=channel,
            template_key=template_key,
            transaction_type=expected.transaction_type,
            account_type=expected.account_type,
            regex=regex_str,
            date_regex=date_regex,
            synthetic_sample=result.synthetic_sample or '',
            synthetic_expected=json.dumps(result.synthetic_expected or {}),
            fingerprint=fp,
            proposal_id=proposal_id,
        )
        if fp:
            self._store.upsert_fingerprint_state(fp, 'learned')
        self._store.log_proposal(proposal_id, 'pattern', 'accepted', [])
        self._registry.force_reload()

        self._write_result(
            proposal_id,
            'accepted',
            [],
            pattern_id=pattern_id,
            template_id=f'learned:{pattern_id}',
        )
        log.info(
            'inbox: accepted pattern id=%d bank=%s key=%s', pattern_id, bank_slug, template_key
        )

    def _handle_ignore(self, proposal_id: str, data: dict[str, object]) -> None:
        fp = str(data.get('fingerprint', ''))
        if fp:
            self._store.upsert_fingerprint_state(fp, 'ignored')
        self._store.log_proposal(proposal_id, 'ignore', 'accepted', [])
        self._write_result(proposal_id, 'accepted', [], None, None)

    def _handle_feedback(self, proposal_id: str, data: dict[str, object]) -> None:
        pattern_id = data.get('pattern_id')
        verdict = str(data.get('verdict', ''))
        if not isinstance(pattern_id, int) or verdict not in ('wrong', 'correct'):
            self._store.log_proposal(proposal_id, 'feedback', 'rejected', ['schema_invalid'])
            self._write_result(proposal_id, 'rejected', ['schema_invalid'], None, None)
            return

        from forwarder.learning.lifecycle import apply_feedback

        apply_feedback(self._store, pattern_id, verdict)
        self._store.log_proposal(proposal_id, 'feedback', 'accepted', [])
        self._write_result(proposal_id, 'accepted', [], None, None)

    def _write_result(
        self,
        proposal_id: str,
        outcome: str,
        codes: list[str],
        pattern_id: int | None,
        template_id: str | None,
        rejections: list[dict[str, str]] | None = None,
    ) -> None:
        result: dict[str, object] = {
            'version': 1,
            'proposal_id': proposal_id,
            'outcome': outcome,
            'codes': codes,
        }
        if pattern_id is not None:
            result['pattern_id'] = pattern_id
            result['template_id'] = template_id
            result['status'] = 'candidate'
        if rejections:
            result['rejections'] = rejections

        tmp = self._results / f'{proposal_id}.json.tmp'
        final = self._results / f'{proposal_id}.json'
        tmp.write_text(json.dumps(result), encoding='utf-8')
        tmp.rename(final)

    def _write_registry_json(self) -> None:
        try:
            snap = self._registry.snapshot()
            banks_out: list[dict[str, object]] = []
            for bank in snap.banks:
                templates: list[dict[str, object]] = []
                for txn in bank.transactions:
                    templates.append(
                        {
                            'template_id': txn.template_id,
                            'transaction_type': txn.transaction_type,
                            'account_type': txn.account_type,
                            'channel': txn.channel,
                            'status': txn.status,
                            'regex': txn.pattern.pattern,
                        }
                    )
                banks_out.append(
                    {
                        'slug': bank.name,
                        'country': bank.country,
                        'currency': bank.currency,
                        'thousands_separator': bank.thousands_separator,
                        'decimal_separator': bank.decimal_separator,
                        'sms_prefix': bank.sms_prefix.pattern if bank.sms_prefix else None,
                        'date_regex': bank.date.pattern,
                        'templates': templates,
                    }
                )
            doc = {'version': snap.version, 'banks': banks_out}
            tmp = self._registry_json.with_suffix('.json.tmp')
            tmp.write_text(json.dumps(doc, indent=2), encoding='utf-8')
            tmp.rename(self._registry_json)
        except Exception:
            log.warning('inbox: failed to write registry.json')


def _build_bank_from_profile(data: dict[str, object]) -> BankPatterns | None:
    import re as _re
    from datetime import timedelta
    from datetime import timezone as _tz

    from forwarder.sanitizer.banks import BankPatterns

    try:
        slug = str(data['slug'])
        country = str(data.get('country', 'CO'))
        currency = str(data['currency'])
        tsep = str(data['thousands_separator'])
        dsep = str(data['decimal_separator'])
        offset = int(data['utc_offset_minutes'])  # type: ignore[arg-type]
        local_tz = _tz(timedelta(minutes=offset))
        sms_prefix_str = data.get('sms_prefix')
        sms_prefix = _re.compile(str(sms_prefix_str), _re.IGNORECASE) if sms_prefix_str else None
        date_pattern = _re.compile(str(data['date_regex']))
        email_senders_raw = data.get('email_senders', [])
        _es = cast(list[object], email_senders_raw if isinstance(email_senders_raw, list) else [])
        email_senders: frozenset[str] = frozenset(str(s) for s in _es)
        app_names_raw = data.get('app_names', [])
        _an = cast(list[object], app_names_raw if isinstance(app_names_raw, list) else [])
        app_names: frozenset[str] = frozenset(str(a) for a in _an)
        return BankPatterns(
            name=slug,
            country=country,
            currency=currency,
            thousands_separator=tsep,
            decimal_separator=dsep,
            email_senders=email_senders,
            sms_prefix=sms_prefix,
            date=date_pattern,
            transactions=(),
            local_timezone=local_tz,
            app_names=app_names,
        )
    except (KeyError, ValueError, TypeError):
        return None


def _tz_to_minutes(tz: object) -> int:
    from datetime import timezone as _tz

    if isinstance(tz, _tz):
        return int(tz.utcoffset(None).total_seconds() // 60)  # type: ignore[union-attr]
    return 0
