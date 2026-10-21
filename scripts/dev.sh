#!/usr/bin/env bash
# HushMoney — local development launcher
#
# Starts the full stack on your local machine. Handles OpenShell sandbox setup
# automatically on first run. Safe to re-run — every step is idempotent.
#
# Usage:
#   ./scripts/dev.sh                  # start with OpenShell sandbox (default)
#   ./scripts/dev.sh --no-openshell   # plain podman compose (no sandboxing)
#   ./scripts/dev.sh --down           # stop and remove everything
#   ./scripts/dev.sh --logs           # tail logs from the running stack
#
# Prerequisites: .env filled in (run once: cp .env.example .env && $EDITOR .env)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"
SANDBOX_NAME="hushmoney-1"
BOX_NAME="hushmoney"

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

# Run a command inside the Ubuntu distrobox where k3s/kubelet work properly.
box() { distrobox run --name "$BOX_NAME" -- env DOCKER_HOST="unix:///run/podman/podman.sock" "$@"; }

box_exists()     { distrobox list 2>/dev/null | grep -q "$BOX_NAME"; }
sandbox_exists() { box openshell sandbox list 2>/dev/null | grep -q "$SANDBOX_NAME"; }


# ── Down ───────────────────────────────────────────────────────────────────────

if [[ "$MODE" == down ]]; then
    info "Stopping forwarder..."
    podman compose down 2>/dev/null || true

    if box_exists && sandbox_exists; then
        info "Stopping OpenShell sandbox..."
        box openshell sandbox delete "$SANDBOX_NAME" 2>/dev/null || true
    fi

    info "Done."
    exit 0
fi

# ── Logs ───────────────────────────────────────────────────────────────────────

if [[ "$MODE" == logs ]]; then
    if box_exists && sandbox_exists; then
        info "Hermes sandbox logs (ctrl-c to exit):"
        box openshell logs "$SANDBOX_NAME" --tail &
        HERMES_LOG_PID=$!
    else
        info "Hermes container logs (ctrl-c to exit):"
        podman logs -f hermes &
        HERMES_LOG_PID=$!
    fi

    info "Forwarder logs:"
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
    load_env  # reload so the new value is available for the rest of the script
fi

# ── Plain mode (--no-openshell) ────────────────────────────────────────────────

if [[ "$USE_OPENSHELL" == false ]]; then
    info "Starting stack without OpenShell sandbox..."
    HERMES_UID=$(id -u) HERMES_GID=$(id -g) podman compose up -d --build
    info "Stack running."
    echo ""
    echo "  Logs:     ./scripts/dev.sh --logs"
    echo "  Stop:     ./scripts/dev.sh --down"
    echo "  Gateway:  curl -s -X POST http://localhost:8080/gateway \\"
    echo "              -H 'Authorization: Bearer \$HERMES_GATEWAY_SECRET' \\"
    echo "              -H 'Content-Type: application/json' \\"
    echo "              -d '{\"transaction_type\":\"debit\",\"amount\":45000,\"currency\":\"COP\",\"merchant\":\"RAPPI\",\"channel\":\"email\"}'"
    echo ""
    exit 0
fi

# ── OpenShell mode (default) ───────────────────────────────────────────────────

# Step 1: Create Ubuntu distrobox if missing (k3s/kubelet work correctly inside it)
if ! box_exists; then
    info "Creating Ubuntu distrobox '$BOX_NAME' (one-time setup)..."
    distrobox create --name "$BOX_NAME" --image ubuntu:24.04 --yes
    distrobox enter "$BOX_NAME" -- true  # initialise the box
fi

# Step 2: Install OpenShell inside the box if missing
if ! box openshell version &>/dev/null; then
    info "Installing OpenShell inside '$BOX_NAME'..."
    box bash -c "curl -LsSf https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh | sh"
fi

# Step 3: Ensure gateway is running inside the box
if ! box openshell provider list &>/dev/null; then
    info "Starting OpenShell gateway..."
    box openshell gateway start
fi

# Step 4: Register Nebius inference provider (idempotent)
if ! box openshell provider list 2>/dev/null | grep -q "nebius"; then
    info "Registering Nebius inference provider..."
    [[ -z "${NEBIUS_API_KEY:-}" ]] && error "NEBIUS_API_KEY not set in .env"
    box openshell provider create \
        --name nebius \
        --type openai \
        --credential "NEBIUS_API_KEY=$NEBIUS_API_KEY" \
        --config "base_url=https://api.studio.nebius.ai/v1/"
else
    info "Nebius provider already registered."
fi

# Step 5: Create sandbox — reuse if already running to skip the image pull.
if sandbox_exists; then
    info "Sandbox $SANDBOX_NAME already exists — reusing it."
else
    info "Creating sandbox $SANDBOX_NAME..."
    box openshell sandbox create \
        --from ghcr.io/alejandroblanco2001/untyped:latest \
        --name "$SANDBOX_NAME" \
        --policy "$REPO_ROOT/config/openshell/policy.yaml" \
        --provider nebius \
        --upload "$ENV_FILE":/app/.env \
        -- /app/docker-entrypoint.sh &
    info "Hermes sandbox starting in background."
fi

# Step 5: Start forwarder via podman compose (runs outside the sandbox)
# --no-deps skips starting the hermes compose service — Hermes already runs
# inside the OpenShell sandbox on port 8080.
info "Starting forwarder..."
HERMES_UID=$(id -u) HERMES_GID=$(id -g) podman compose up -d --no-deps forwarder

# ── Done ───────────────────────────────────────────────────────────────────────

echo ""
info "Stack running with OpenShell sandbox."
echo ""
echo "  Sandbox:  openshell sandbox list"
echo "  Logs:     ./scripts/dev.sh --logs"
echo "  Stop:     ./scripts/dev.sh --down"
echo ""
echo "  Test the gateway:"
echo "    source .env"
echo "    curl -s -X POST http://localhost:8080/gateway \\"
echo "      -H 'Authorization: Bearer \$HERMES_GATEWAY_SECRET' \\"
echo "      -H 'Content-Type: application/json' \\"
echo "      -d '{\"transaction_type\":\"debit\",\"amount\":45000,\"currency\":\"COP\",\"merchant\":\"RAPPI\",\"channel\":\"email\"}'"
echo ""
