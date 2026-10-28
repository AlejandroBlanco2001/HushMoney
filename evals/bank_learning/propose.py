#!/usr/bin/env python3
"""
bank_learning eval: proposal/ignore files written to the inbox are well-formed.

No API key required — fully offline. (The LLM's pattern *inference* quality is
covered separately under evals/model_selection/bank_learning.py; pattern
*validation* is covered by the forwarder's pytest suite. This guards the contract
between the skill scripts and the forwarder inbox.)

Covers:
  - propose_pattern writes a kind=pattern proposal with expected parsed to JSON,
    carrying date_regex and bank_profile through when supplied
  - invalid --expected JSON fails without writing a file
  - mark_ignored writes a kind=ignore proposal

Usage:
    python evals/bank_learning/propose.py
    python evals/bank_learning/propose.py -v
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent))
from lib import models as _models


REPO_ROOT = _models.REPO_ROOT
SCRIPTS = REPO_ROOT / 'skills/bank_learning/scripts'

_TOTAL = 0
_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = '') -> None:
    global _TOTAL
    _TOTAL += 1
    print(f'  {"✓" if cond else "✗"} {name}' + ('' if cond else f'  — {detail}'))
    if not cond:
        _FAILURES.append(name)


def run(script: str, *args: str, inbox: str, verbose: bool = False) -> dict:
    env = {**os.environ, 'HUSHMONEY_INBOX': inbox}
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


def _read_proposal(inbox: str, proposal_id: str) -> dict:
    path = Path(inbox) / 'proposals' / f'{proposal_id}.json'
    return json.loads(path.read_text()) if path.exists() else {}


def main(verbose: bool = False) -> None:
    with tempfile.TemporaryDirectory() as inbox:
        print('\nbank_learning propose/ignore eval\n')

        expected = json.dumps(
            {
                'amount': 123456.78,
                'transaction_type': 'debit',
                'account_type': 'checking',
                'date': '2026-01-02T10:20:00Z',
            }
        )
        res = run(
            'propose_pattern.py',
            '--bank',
            'davivienda',
            '--channel',
            'sms',
            '--template-key',
            'debit_checking',
            '--regex',
            r'(?P<amount>[\d.,]+) COMPRA',
            '--sample',
            'COMPRA por $123.456,78 en TIENDA',
            '--fingerprint',
            'abc123',
            '--expected',
            expected,
            '--date-regex',
            r'(?P<day>\d{2})/(?P<month>\d{2})/(?P<year>\d{4})',
            '--bank-profile',
            json.dumps({'slug': 'davivienda', 'currency': 'COP'}),
            inbox=inbox,
            verbose=verbose,
        )
        check('propose_ok', res.get('ok') is True and 'proposal_id' in res, str(res))

        doc = _read_proposal(inbox, res.get('proposal_id', '')) if res.get('ok') else {}
        check('proposal_file_written', bool(doc), 'no file')
        check('proposal_kind_pattern', doc.get('kind') == 'pattern', str(doc.get('kind')))
        check(
            'proposal_user_confirmed',
            doc.get('user_confirmed') is True,
            str(doc.get('user_confirmed')),
        )
        check(
            'proposal_expected_parsed',
            isinstance(doc.get('expected'), dict) and doc['expected'].get('amount') == 123456.78,
            str(doc.get('expected')),
        )
        check('proposal_carries_date_regex', 'date_regex' in doc, str(list(doc)))
        check(
            'proposal_carries_bank_profile',
            isinstance(doc.get('bank_profile'), dict)
            and doc['bank_profile'].get('slug') == 'davivienda',
            str(doc.get('bank_profile')),
        )

        before = len(list((Path(inbox) / 'proposals').glob('*.json')))
        bad = run(
            'propose_pattern.py',
            '--bank',
            'davivienda',
            '--channel',
            'sms',
            '--template-key',
            'x',
            '--regex',
            '(?P<amount>.+)',
            '--sample',
            's',
            '--fingerprint',
            'f',
            '--expected',
            'not-json',
            inbox=inbox,
            verbose=verbose,
        )
        after = len(list((Path(inbox) / 'proposals').glob('*.json')))
        check('invalid_expected_rejected', bad.get('ok') is False and 'error' in bad, str(bad))
        check('invalid_expected_writes_no_file', after == before, f'{before}->{after}')

        ign = run('mark_ignored.py', '--fingerprint', 'deadbeef', inbox=inbox, verbose=verbose)
        ign_doc = _read_proposal(inbox, ign.get('proposal_id', '')) if ign.get('ok') else {}
        check('ignore_ok', ign.get('ok') is True, str(ign))
        check(
            'ignore_kind_and_fingerprint',
            ign_doc.get('kind') == 'ignore' and ign_doc.get('fingerprint') == 'deadbeef',
            str(ign_doc),
        )

        print(f'\n  {_TOTAL - len(_FAILURES)}/{_TOTAL} passed')
        if _FAILURES:
            sys.exit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', '--verbose', action='store_true')
    main(verbose=parser.parse_args().verbose)
