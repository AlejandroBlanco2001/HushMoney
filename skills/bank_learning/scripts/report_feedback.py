"""
Report whether a learned pattern produced a correct or wrong result.

Usage:
  python3 report_feedback.py --pattern-id 42 --verdict correct
  python3 report_feedback.py --pattern-id 42 --verdict wrong

Output: {"ok": true, "proposal_id": "..."}
"""

from __future__ import annotations

import argparse
import json
import os
import uuid
from pathlib import Path


INBOX_DIR = os.environ.get('HUSHMONEY_INBOX', os.path.expanduser('~/.hermes/pattern-inbox'))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--pattern-id', required=True, type=int)
    parser.add_argument('--verdict', required=True, choices=['correct', 'wrong'])
    args = parser.parse_args()

    proposal_id = str(uuid.uuid4())
    proposal: dict[str, object] = {
        'version': 1,
        'kind': 'feedback',
        'proposal_id': proposal_id,
        'pattern_id': args.pattern_id,
        'verdict': args.verdict,
    }

    proposals_dir = Path(INBOX_DIR) / 'proposals'
    proposals_dir.mkdir(parents=True, exist_ok=True)
    tmp = proposals_dir / f'{proposal_id}.json.tmp'
    final = proposals_dir / f'{proposal_id}.json'
    tmp.write_text(json.dumps(proposal), encoding='utf-8')
    tmp.rename(final)

    print(json.dumps({'ok': True, 'proposal_id': proposal_id}))


if __name__ == '__main__':
    main()
