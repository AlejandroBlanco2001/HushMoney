#!/usr/bin/env bash
# HushMoney — local development launcher
#
# Usage:
#   ./scripts/dev.sh                  # start with OpenShell sandbox (default)
#   ./scripts/dev.sh --no-openshell   # plain podman compose (no sandboxing)
#   ./scripts/dev.sh --down           # stop and remove everything
#   ./scripts/dev.sh --logs           # tail logs from the running stack
#
# Prerequisites: .env filled in (cp .env.example .env && $EDITOR .env)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"
SANDBOX_NAME="hushmoney-1"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[dev]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC} $*"; }
error() { echo -e "${RED}[error]${NC} $*" >&2; exit 1; }

# ── Argument parsing ───────────────────────────────────────────────────────────

USE_OPENSHELL=true
MODE=up

for arg in "$@"; do
    case $arg in
        --no-openshell) USE_OPENSHELL=false ;;
        --down)         MODE=down ;;
        --logs)         MODE=logs ;;
        *) error "Unknown argument: $arg. Usage: dev.sh [--no-openshell] [--down] [--logs]" ;;
    esac
done

# ── Helpers ────────────────────────────────────────────────────────────────────

load_env() {
    [[ -f "$ENV_FILE" ]] || error ".env not found. Run: cp .env.example .env && \$EDITOR .env"
    set -a; source "$ENV_FILE"; set +a
}

sandbox_exists() { openshell sandbox list 2>/dev/null | grep -q "$SANDBOX_NAME"; }

# ── Down ───────────────────────────────────────────────────────────────────────

if [[ "$MODE" == down ]]; then
    info "Stopping forwarder..."
    DOCKER_HOST="unix:///run/podman/podman.sock" podman compose down 2>/dev/null || true

    if sandbox_exists; then
        info "Stopping OpenShell sandbox..."
        openshell sandbox delete "$SANDBOX_NAME" 2>/dev/null || true
    fi

    info "Done."
    exit 0
fi

# ── Logs ───────────────────────────────────────────────────────────────────────

if [[ "$MODE" == logs ]]; then
    if sandbox_exists; then
        info "Hermes sandbox logs (ctrl-c to exit):"
        openshell logs "$SANDBOX_NAME" --tail &
        HERMES_LOG_PID=$!
    else
        podman logs -f hermes &
        HERMES_LOG_PID=$!
    fi

    podman logs -f hushmoney-forwarder-1 &
    FORWARDER_LOG_PID=$!

    trap "kill $HERMES_LOG_PID $FORWARDER_LOG_PID 2>/dev/null; exit 0" INT TERM
    wait
    exit 0
fi

# ── Up ─────────────────────────────────────────────────────────────────────────

load_env

# ── Telegram session ───────────────────────────────────────────────────────────

if [[ -z "${TELEGRAM_SESSION_STRING:-}" ]]; then
    info "No TELEGRAM_SESSION_STRING found — generating one now."
    info "You will be prompted for your phone number and a Telegram OTP."
    uv run --python cpython-3.12 --with pyrogram --with python-dotenv \
        python "$REPO_ROOT/scripts/gen_session.py" "$ENV_FILE"
    load_env
fi

# ── Plain mode (--no-openshell) ────────────────────────────────────────────────

if [[ "$USE_OPENSHELL" == false ]]; then
    info "Starting stack without OpenShell sandbox..."
    HERMES_UID=$(id -u) HERMES_GID=$(id -g) \
        DOCKER_HOST="unix:///run/podman/podman.sock" podman compose up -d --build
    info "Stack running. Logs: ./scripts/dev.sh --logs"
    exit 0
fi

# ── OpenShell mode (default) ───────────────────────────────────────────────────

# Connect to gateway if not already done
if ! openshell sandbox list &>/dev/null; then
    info "Connecting to OpenShell gateway..."
    openshell gateway add https://127.0.0.1:8080 --local --gateway-insecure 2>/dev/null || true
    openshell gateway select openshell 2>/dev/null || true
fi

# Create sandbox — reuse if already running
if sandbox_exists; then
    info "Sandbox $SANDBOX_NAME already exists — reusing it."
else
    info "Creating sandbox $SANDBOX_NAME..."
    openshell sandbox create \
        --from ghcr.io/alejandroblanco2001/untyped:latest \
        --name "$SANDBOX_NAME" \
        --policy "$REPO_ROOT/config/openshell/policy.yaml" \
        --provider nebius \
        -- /app/docker-entrypoint.sh &
    info "Hermes sandbox starting in background."
fi

# Start forwarder — Hermes runs in the OpenShell sandbox on port 8080
info "Starting forwarder..."
HERMES_UID=$(id -u) HERMES_GID=$(id -g) \
    DOCKER_HOST="unix:///run/podman/podman.sock" podman compose up -d --no-deps forwarder

# ── Done ───────────────────────────────────────────────────────────────────────

echo ""
info "Stack running."
echo ""
echo "  Sandbox:  openshell sandbox list"
echo "  Logs:     ./scripts/dev.sh --logs"
echo "  Stop:     ./scripts/dev.sh --down"
echo ""
echo "  Test:"
echo "    source .env && curl -s -X POST http://localhost:8081/gateway \\"
echo "      -H 'Authorization: Bearer \$HERMES_GATEWAY_SECRET' \\"
echo "      -H 'Content-Type: application/json' \\"
echo "      -d '{\"transaction_type\":\"debit\",\"amount\":45000,\"currency\":\"COP\",\"merchant\":\"RAPPI\",\"channel\":\"email\"}'"
echo ""
