#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ $# -eq 0 ]]; then
    set -- forwarder/tests
fi
uv run --project forwarder --python 3.12 python -m pytest -c forwarder/pyproject.toml "$@"
