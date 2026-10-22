#!/usr/bin/env bash
# Seed the demo database with realistic fake transactions.
#
# Run from the repo root after the stack is up:
#   ./scripts/seed_demo.sh
#
# Safe to run multiple times — existing rows are skipped.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[seed]${NC} $*"; }
error() { echo -e "${RED}[error]${NC} $*" >&2; exit 1; }

if ! docker ps --format '{{.Names}}' | grep -q '^hermes$'; then
    error "hermes container is not running. Start the stack first: docker compose up -d"
fi

info "Copying seed script into container..."
docker cp "$REPO_ROOT/scripts/seed_demo.py" hermes:/tmp/seed_demo.py

info "Running seed..."
RESULT=$(docker exec hermes python3 /tmp/seed_demo.py)

TRANSACTIONS=$(echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['transactions'])")
ACCOUNTS=$(echo "$RESULT"     | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['accounts'])")
DEBTS=$(echo "$RESULT"        | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['debts'])")

info "Done. DB now has $TRANSACTIONS transactions, $ACCOUNTS accounts, $DEBTS debts."
