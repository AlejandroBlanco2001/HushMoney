"""
Read current bank registry for Hermes context.

Usage: python3 get_bank_context.py [--bank SLUG]
Output: JSON with bank list or single bank detail.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


REGISTRY_PATH = os.environ.get(
    'HUSHMONEY_REGISTRY', os.path.expanduser('~/.hermes/pattern-inbox/registry.json')
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--bank', help='Filter to a specific bank slug')
    args = parser.parse_args()

    path = Path(REGISTRY_PATH)
    if not path.exists():
        print(json.dumps({'error': 'registry.json not found', 'banks': []}))
        return

    try:
        registry: dict[str, object] = json.loads(path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError) as exc:
        print(json.dumps({'error': str(exc), 'banks': []}))
        return

    banks: list[object] = registry.get('banks', [])  # type: ignore[assignment]
    if args.bank:
        banks = [b for b in banks if isinstance(b, dict) and b.get('slug') == args.bank]

    print(json.dumps({'version': registry.get('version'), 'banks': banks}, indent=2))


if __name__ == '__main__':
    main()
