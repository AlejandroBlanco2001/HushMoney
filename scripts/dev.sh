#!/usr/bin/env bash
# HushMoney — local development launcher
#
# Usage:
#   ./scripts/dev.sh                             # OpenShell sandbox (default)
#   ./scripts/dev.sh --no-openshell              # plain podman compose, full stack
#   ./scripts/dev.sh --no-openshell --no-telemetry # full stack without OpenObserve
#   ./scripts/dev.sh --no-openshell --local-models # full stack + local Ollama (local-llm profile)
#   ./scripts/dev.sh --down                      # stop and remove everything
#   ./scripts/dev.sh --logs                      # tail logs from the running stack
#
# The LLM telemetry proxy always runs inside the hermes container; --no-telemetry
# only skips the OpenObserve sink (the proxy then forwards without recording).
# Telemetry applies to --no-openshell mode only (OpenShell runs a prebuilt image).
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
TELEMETRY=true
LOCAL_MODELS=false
MODE=up

for arg in "$@"; do
    case $arg in
        --no-openshell) USE_OPENSHELL=false ;;
        --no-telemetry) TELEMETRY=false ;;
        --local-models) LOCAL_MODELS=true ;;
        --down)         MODE=down ;;
        --logs)         MODE=logs ;;
        *) error "Unknown argument: $arg. Usage: dev.sh [--no-openshell] [--no-telemetry] [--local-models] [--down] [--logs]" ;;
    esac
done

export DOCKER_HOST="unix:///run/podman/podman.sock"

# ── Helpers ────────────────────────────────────────────────────────────────────

load_env() {
    [[ -f "$ENV_FILE" ]] || error ".env not found. Run: cp .env.example .env && \$EDITOR .env"
    set -a; source "$ENV_FILE"; set +a
}

sandbox_exists() { openshell sandbox list 2>/dev/null | grep -q "$SANDBOX_NAME"; }

# ── Down ───────────────────────────────────────────────────────────────────────

if [[ "$MODE" == down ]]; then
    info "Stopping forwarder..."
    # Name every profile so the OpenObserve + Ollama containers are torn down too.
    podman compose --profile telemetry --profile local-llm down 2>/dev/null || true

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
    export HERMES_UID HERMES_GID
    HERMES_UID=$(id -u)
    HERMES_GID=$(id -g)

    # Compose profiles: telemetry → OpenObserve, local-llm → the Ollama service.
    PROFILE_ARGS=()
    [[ "$TELEMETRY" == true ]] && PROFILE_ARGS+=(--profile telemetry)
    [[ "$LOCAL_MODELS" == true ]] && PROFILE_ARGS+=(--profile local-llm)

    if [[ "$TELEMETRY" == true ]]; then
        info "Starting full stack (with telemetry → OpenObserve)..."
        podman compose "${PROFILE_ARGS[@]}" up -d --build
    else
        info "Starting full stack (telemetry sink disabled)..."
        # Empty OPENOBSERVE_URL makes the in-container proxy a no-op recorder.
        OPENOBSERVE_URL='' podman compose "${PROFILE_ARGS[@]}" up -d --build
    fi

    echo ""
    info "Stack running."
    echo "  Logs:       ./scripts/dev.sh --logs"
    echo "  Stop:       ./scripts/dev.sh --down"
    [[ "$TELEMETRY" == true ]] && echo "  Telemetry:  http://127.0.0.1:5080  (OpenObserve)"
    if [[ "$LOCAL_MODELS" == true ]]; then
        echo "  Local LLM:  http://127.0.0.1:11434  (Ollama)"
        echo "    First run: podman compose exec ollama ollama pull gemma4:e4b"
        echo "    Then set in .env: CATEGORIZER_BASE_URL=http://ollama:11434/v1 CATEGORIZER_MODEL=gemma4:e4b"
    fi
    echo ""
    echo "  Smoke test a transaction:"
    echo "    make smoke   # or the curl in 'make help'"
    echo ""
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
