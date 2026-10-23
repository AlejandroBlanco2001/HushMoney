"""
Mark a fingerprint as ignored so it is never forwarded again.

Usage: python3 mark_ignored.py --fingerprint abc123def456

Output: {"ok": true, "proposal_id": "..."}
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
    parser.add_argument('--fingerprint', required=True)
    args = parser.parse_args()

    proposal_id = str(uuid.uuid4())
    proposal: dict[str, object] = {
        'version': 1,
        'kind': 'ignore',
        'proposal_id': proposal_id,
        'fingerprint': args.fingerprint,
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
