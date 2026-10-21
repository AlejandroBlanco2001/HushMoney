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

sandbox_setting_set() {
    local sandbox="$1" key="$2" value="$3"
    openshell settings set "$sandbox" --key "$key" --value "$value" 2>/dev/null || \
        warn "Could not set setting $key on sandbox $sandbox"
}

sandbox_exists() {
    openshell sandbox list 2>/dev/null | grep -q "$SANDBOX_NAME"
}


# ── Down ───────────────────────────────────────────────────────────────────────

if [[ "$MODE" == down ]]; then
    info "Stopping forwarder..."
    podman compose down 2>/dev/null || true

    if command -v openshell &>/dev/null && sandbox_exists; then
        info "Stopping OpenShell sandbox..."
        openshell sandbox delete "$SANDBOX_NAME" 2>/dev/null || true
    fi

    info "Done."
    exit 0
fi

# ── Logs ───────────────────────────────────────────────────────────────────────

if [[ "$MODE" == logs ]]; then
    if command -v openshell &>/dev/null && sandbox_exists; then
        info "Hermes sandbox logs (ctrl-c to exit):"
        openshell logs "$SANDBOX_NAME" --tail &
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

# Step 1: Install OpenShell if missing
if ! command -v openshell &>/dev/null; then
    info "Installing OpenShell..."
    curl -LsSf https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh | sh
    # Reload PATH in case the installer added a new directory
    export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"
fi

# Rootful Podman socket — required for OpenShell (k3s kubelet needs /dev/kmsg,
# which is blocked in rootless user-namespace containers on NixOS)
export DOCKER_HOST="unix:///run/podman/podman.sock"

# Step 2: Ensure gateway is running (auto-starts if needed)
# openshell status exits 0 even with no active gateway; provider list requires one
if ! openshell provider list &>/dev/null; then
    info "Starting OpenShell gateway..."
    openshell gateway start
fi

# Step 3: Register Nebius inference provider (idempotent)
if ! openshell provider list 2>/dev/null | grep -q "nebius"; then
    info "Registering Nebius inference provider..."
    [[ -z "${NEBIUS_API_KEY:-}" ]] && error "NEBIUS_API_KEY not set in .env"
    openshell provider create \
        --name nebius \
        --type openai \
        --credential "NEBIUS_API_KEY=$NEBIUS_API_KEY" \
        --config "base_url=https://api.studio.nebius.ai/v1/"
else
    info "Nebius provider already registered."
fi

# Step 4: (Re)create sandbox from our Dockerfile
# Secrets are uploaded via .env; policy is applied inline at create time.
if sandbox_exists; then
    info "Removing existing sandbox..."
    openshell sandbox delete "$SANDBOX_NAME" 2>/dev/null || true
fi

info "Creating sandbox $SANDBOX_NAME..."
openshell sandbox create \
    --from ghcr.io/alejandroblanco2001/untyped:latest \
    --name "$SANDBOX_NAME" \
    --policy "$REPO_ROOT/config/openshell/policy.yaml" \
    --provider nebius \
    --upload "$ENV_FILE":/app/.env \
    -- /app/docker-entrypoint.sh &
SANDBOX_PID=$!
info "Hermes sandbox started (PID $SANDBOX_PID)."

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
