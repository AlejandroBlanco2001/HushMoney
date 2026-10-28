#!/usr/bin/env python3
"""
setup eval: user_settings persistence, completion flags, email config, accounts.

No API key required — fully offline.

Covers what would silently break onboarding or leak a secret:
  - save_setting upserts (insert then update, one row)
  - mark_setup_complete sets the completion flags
  - save_email_config persists config but NEVER stores the IMAP password
  - save_accounts is idempotent and links a card
  - a brand-new DB gets the default categories on boot, so categorized
    transactions pass the foreign key (and removed ones are not re-seeded)

Usage:
    python evals/setup/settings.py
    python evals/setup/settings.py -v
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent))
from lib import db as _db
from lib import models as _models


REPO_ROOT = _models.REPO_ROOT
SCRIPTS = REPO_ROOT / 'skills/setup/scripts'

_TOTAL = 0
_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = '') -> None:
    global _TOTAL
    _TOTAL += 1
    print(f'  {"✓" if cond else "✗"} {name}' + ('' if cond else f'  — {detail}'))
    if not cond:
        _FAILURES.append(name)


def run(script: str, *args: str, db_path: str, verbose: bool = False) -> dict:
    env = {
        **os.environ,
        'HUSHMONEY_DB': db_path,
        'HUSHMONEY_SCHEMA': str(REPO_ROOT / 'config/schema.sql'),
    }
    if verbose:
        print(f'    $ {script} {" ".join(args)}')
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args], capture_output=True, text=True, env=env
    )
    if proc.returncode != 0:
        return {'_error': proc.stderr.strip()}
    try:
        out = json.loads(proc.stdout.strip())
    except json.JSONDecodeError:
        return {'_error': f'invalid JSON: {proc.stdout!r}'}
    if verbose:
        print(f'    → {out}')
    return out


def _settings(db_path: str) -> dict[str, str]:
    con = sqlite3.connect(db_path)
    rows = con.execute('SELECT key, value FROM user_settings').fetchall()
    con.close()
    return dict(rows)


def main(verbose: bool = False) -> None:
    with _db.temp_db() as db_path:
        print('\nsetup eval\n')

        run('save_setting.py', 'locale', 'es-CO', db_path=db_path, verbose=verbose)
        run('save_setting.py', 'locale', 'en-US', db_path=db_path, verbose=verbose)
        s = _settings(db_path)
        con = sqlite3.connect(db_path)
        n_locale = con.execute("SELECT COUNT(*) FROM user_settings WHERE key='locale'").fetchone()[
            0
        ]
        con.close()
        check('save_setting_upsert_updates_value', s.get('locale') == 'en-US', str(s.get('locale')))
        check('save_setting_upsert_single_row', n_locale == 1, f'rows={n_locale}')

        run('mark_setup_complete.py', db_path=db_path, verbose=verbose)
        s = _settings(db_path)
        check(
            'setup_complete_flag', s.get('setup_complete') == 'true', str(s.get('setup_complete'))
        )
        check('setup_step_done', s.get('setup_step') == 'done', str(s.get('setup_step')))
        check(
            'setup_completed_at_set',
            bool(s.get('setup_completed_at')),
            str(s.get('setup_completed_at')),
        )

        run(
            'save_email_config.py',
            '--provider',
            'gmail',
            '--host',
            'imap.gmail.com',
            '--port',
            '993',
            '--username',
            'me@gmail.com',
            '--bank-senders',
            'a@bank.com,b@bank.com',
            db_path=db_path,
            verbose=verbose,
        )
        s = _settings(db_path)
        check(
            'email_config_persisted',
            s.get('imap_host') == 'imap.gmail.com'
            and s.get('imap_username') == 'me@gmail.com'
            and s.get('bank_sender_emails') == 'a@bank.com,b@bank.com',
            str(s),
        )
        check('email_config_advances_step', s.get('setup_step') == 'sms', str(s.get('setup_step')))
        # Security: the IMAP password must never be written to the DB.
        pw_keys = [k for k in s if 'password' in k.lower()]
        check('imap_password_not_stored', pw_keys == [], f'found {pw_keys}')

        a1 = run(
            'save_accounts.py',
            '--bank',
            'bancolombia',
            '--type',
            'checking',
            '--currency',
            'COP',
            '--masked-number',
            '****1234',
            '--card-masked-number',
            '****5678',
            '--alias',
            'Debito',
            db_path=db_path,
            verbose=verbose,
        )
        check('account_created', a1.get('created') is True and a1.get('card_id'), str(a1))

        a2 = run(
            'save_accounts.py',
            '--bank',
            'bancolombia',
            '--type',
            'checking',
            '--currency',
            'COP',
            '--masked-number',
            '****1234',
            '--card-masked-number',
            '****5678',
            '--alias',
            'Debito',
            db_path=db_path,
            verbose=verbose,
        )
        check(
            'account_idempotent',
            a2.get('created') is False and a2.get('account_id') == a1.get('account_id'),
            str(a2),
        )

        con = sqlite3.connect(db_path)
        n_acc = con.execute('SELECT COUNT(*) FROM accounts').fetchone()[0]
        n_card = con.execute('SELECT COUNT(*) FROM cards').fetchone()[0]
        con.close()
        check(
            'no_duplicate_account_or_card',
            n_acc == 1 and n_card == 1,
            f'accounts={n_acc} cards={n_card}',
        )

    _check_fresh_db_categories(verbose)

    print(f'\n  {_TOTAL - len(_FAILURES)}/{_TOTAL} passed')
    if _FAILURES:
        sys.exit(1)


def _category_slugs(db_path: str) -> set[str]:
    con = sqlite3.connect(db_path)
    slugs = {row[0] for row in con.execute('SELECT slug FROM categories')}
    con.close()
    return slugs


def _check_fresh_db_categories(verbose: bool) -> None:
    # Starts from a DB file that does not exist yet, like a new container's first
    # boot — temp_db() would hide a missing seed because it applies the schema itself.
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / 'fresh.db')
        run('seed_defaults.py', db_path=db_path, verbose=verbose)
        slugs = _category_slugs(db_path)
        check(
            'fresh_db_has_default_categories',
            len(slugs) == 9 and 'other' in slugs,
            str(sorted(slugs)),
        )

        con = sqlite3.connect(db_path)
        con.execute('PRAGMA foreign_keys = ON')
        try:
            with con:
                con.execute(
                    'INSERT INTO accounts'
                    ' (id, bank, alias, type, currency, masked_number, created_at)'
                    " VALUES ('acc', 'bancolombia', 'Ahorros',"
                    " 'checking', 'COP', '****1234', 'now')"
                )
                con.execute(
                    'INSERT INTO transactions (id, account_id, amount, currency, merchant, date,'
                    ' transaction_type, channel, category, created_at, updated_at)'
                    " VALUES ('tx', 'acc', 1000, 'COP', 'RAPPI', '2026-10-01T00:00:00Z',"
                    " 'debit', 'sms', 'food', 'now', 'now')"
                )
            stored = None
        except sqlite3.IntegrityError as exc:
            stored = str(exc)
        con.execute("DELETE FROM categories WHERE slug = 'other'")
        con.commit()
        con.close()
        check('categorized_tx_passes_foreign_key', stored is None, str(stored))

        run('seed_defaults.py', db_path=db_path, verbose=verbose)
        check(
            'removed_category_not_reseeded_on_boot',
            'other' not in _category_slugs(db_path),
            str(sorted(_category_slugs(db_path))),
        )

        demo = run(
            str(REPO_ROOT / 'scripts/seed_demo.py'),
            db_path=str(Path(tmp) / 'demo.db'),
            verbose=verbose,
        )
        check('seed_demo_works_on_fresh_db', demo.get('ok') is True, str(demo))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', '--verbose', action='store_true')
    main(verbose=parser.parse_args().verbose)
