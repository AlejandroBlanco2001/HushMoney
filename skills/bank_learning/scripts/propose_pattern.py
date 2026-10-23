"""
Submit a regex pattern proposal to the forwarder inbox.

Usage:
  python3 propose_pattern.py \
    --bank davivienda --channel sms \
    --template-key debit_checking \
    --regex '(?P<amount>[\d.,]+).*COMPRA' \
    --sample 'Compra por $123.456,78 en TIENDA' \
    --fingerprint abc123 \
    --expected '{"amount": 123456.78, "transaction_type": "debit", \
                 "account_type": "checking", "date": "2026-01-02T10:20:00Z"}' \
    [--date-regex '(?P<day>\d{2})/(?P<month>\d{2})/(?P<year>\d{4})'] \
    [--bank-profile '{"slug":"davivienda","currency":"COP",...}']

Output: {"ok": true, "proposal_id": "..."} or {"ok": false, "error": "..."}
"""
from __future__ import annotations

import argparse
import json
import os
import uuid
from pathlib import Path


INBOX_DIR = os.environ.get(
    'HUSHMONEY_INBOX', os.path.expanduser('~/.hermes/pattern-inbox')
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--bank', required=True)
    parser.add_argument('--channel', required=True, choices=['sms', 'email', 'any'])
    parser.add_argument('--template-key', required=True)
    parser.add_argument('--regex', required=True)
    parser.add_argument('--sample', required=True)
    parser.add_argument('--fingerprint', required=True)
    parser.add_argument('--expected', required=True, help='JSON with amount, transaction_type, account_type, date')
    parser.add_argument('--date-regex', default=None)
    parser.add_argument('--bank-profile', default=None, help='JSON bank profile for unknown banks')
    args = parser.parse_args()

    try:
        expected: object = json.loads(args.expected)
    except json.JSONDecodeError as exc:
        print(json.dumps({'ok': False, 'error': f'Invalid --expected JSON: {exc}'}))
        return

    if args.bank_profile:
        try:
            bank_profile: object = json.loads(args.bank_profile)
        except json.JSONDecodeError as exc:
            print(json.dumps({'ok': False, 'error': f'Invalid --bank-profile JSON: {exc}'}))
            return
    else:
        bank_profile = None

    proposal_id = str(uuid.uuid4())
    proposal: dict[str, object] = {
        'version': 1,
        'kind': 'pattern',
        'proposal_id': proposal_id,
        'user_confirmed': True,
        'bank_slug': args.bank,
        'channel': args.channel,
        'template_key': args.template_key,
        'regex': args.regex,
        'sample': args.sample,
        'fingerprint': args.fingerprint,
        'expected': expected,
    }
    if args.date_regex:
        proposal['date_regex'] = args.date_regex
    if bank_profile is not None:
        proposal['bank_profile'] = bank_profile

    proposals_dir = Path(INBOX_DIR) / 'proposals'
    proposals_dir.mkdir(parents=True, exist_ok=True)
    tmp = proposals_dir / f'{proposal_id}.json.tmp'
    final = proposals_dir / f'{proposal_id}.json'
    tmp.write_text(json.dumps(proposal), encoding='utf-8')
    tmp.rename(final)

    print(json.dumps({'ok': True, 'proposal_id': proposal_id}))


if __name__ == '__main__':
    main()
