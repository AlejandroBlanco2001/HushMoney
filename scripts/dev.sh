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
PROFILE_NAME="hushmoney"
POLICY_NAME="hushmoney"
GATEWAY_TOML="$HOME/.config/openshell/gateway.toml"

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

openshell_secret_set() {
    local name="$1" value="$2"
    # set is idempotent — creates or updates
    openshell secret set "$name" "$value" 2>/dev/null || \
        warn "Could not set secret $name — check openshell status"
}

sandbox_exists() {
    openshell sandbox list 2>/dev/null | grep -q "$SANDBOX_NAME"
}

sandbox_running() {
    openshell sandbox list 2>/dev/null | grep "$SANDBOX_NAME" | grep -q "running"
}

# ── Down ───────────────────────────────────────────────────────────────────────

if [[ "$MODE" == down ]]; then
    info "Stopping forwarder..."
    podman compose down 2>/dev/null || true

    if command -v openshell &>/dev/null && sandbox_exists; then
        info "Stopping OpenShell sandbox..."
        openshell sandbox stop "$SANDBOX_NAME" 2>/dev/null || true
        openshell sandbox delete "$SANDBOX_NAME" 2>/dev/null || true
    fi

    info "Done."
    exit 0
fi

# ── Logs ───────────────────────────────────────────────────────────────────────

if [[ "$MODE" == logs ]]; then
    if command -v openshell &>/dev/null && sandbox_exists; then
        info "Hermes sandbox logs (ctrl-c to exit):"
        openshell sandbox logs "$SANDBOX_NAME" --follow &
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

openshell status &>/dev/null || error "OpenShell gateway is not running. Try: systemctl --user start openshell"

# Step 2: Gateway config
if [[ ! -f "$GATEWAY_TOML" ]]; then
    info "Installing OpenShell gateway config..."
    mkdir -p "$(dirname "$GATEWAY_TOML")"
    cp "$REPO_ROOT/config/openshell/gateway.toml" "$GATEWAY_TOML"
    openshell-gateway config preflight --path "$GATEWAY_TOML" || \
        warn "Config preflight failed — gateway may need a restart: systemctl --user restart openshell"
fi

# Step 3: Register Nebius inference provider (idempotent)
if ! openshell provider list 2>/dev/null | grep -q "nebius"; then
    info "Registering Nebius inference provider..."
    [[ -z "${NEBIUS_API_KEY:-}" ]] && error "NEBIUS_API_KEY not set in .env"
    openshell provider create nebius \
        --endpoint https://api.studio.nebius.ai/v1/ \
        --api-key "$NEBIUS_API_KEY"
else
    info "Nebius provider already registered."
fi

# Step 4: Push secrets into OpenShell (replaces writing them to .env on the host)
info "Syncing secrets into OpenShell..."
openshell_secret_set TELEGRAM_BOT_TOKEN  "$TELEGRAM_BOT_TOKEN"
openshell_secret_set TELEGRAM_CHAT_ID    "$TELEGRAM_CHAT_ID"
openshell_secret_set HERMES_GATEWAY_SECRET "${HERMES_GATEWAY_SECRET:-}"

# Step 5: Apply policy
info "Applying sandbox policy..."
openshell policy set "$POLICY_NAME" \
    --policy "$REPO_ROOT/config/openshell/policy.yaml" --wait

# Step 6: Register/update profile
info "Registering sandbox profile..."
if openshell profile list 2>/dev/null | grep -q "$PROFILE_NAME"; then
    openshell profile update "$REPO_ROOT/config/openshell/profile.yaml" 2>/dev/null || \
        openshell profile register "$REPO_ROOT/config/openshell/profile.yaml"
else
    openshell profile register "$REPO_ROOT/config/openshell/profile.yaml"
fi

# Step 7: Build hermes image
info "Building hermes image..."
podman build -t hushmoney-hermes "$REPO_ROOT"

# Step 8: (Re)create sandbox
if sandbox_exists; then
    info "Recreating sandbox..."
    openshell sandbox stop  "$SANDBOX_NAME" 2>/dev/null || true
    openshell sandbox delete "$SANDBOX_NAME" 2>/dev/null || true
fi

info "Creating sandbox $SANDBOX_NAME..."
openshell sandbox create --from "$PROFILE_NAME" --name "$SANDBOX_NAME"

# Step 9: Start forwarder via podman compose (runs outside the sandbox)
info "Starting forwarder..."
HERMES_UID=$(id -u) HERMES_GID=$(id -g) podman compose up -d forwarder

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
