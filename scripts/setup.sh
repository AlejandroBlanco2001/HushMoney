#!/usr/bin/env bash
# HushMoney — one-shot environment setup
#
# What this does:
#   1. Checks required tools are installed
#   2. Ensures .env exists and is populated
#   3. Bootstraps the EC2 instance (Docker + repo, first run only)
#   4. Pushes secrets to the EC2 instance and starts the stack
#
# Prerequisites (one-time, done by the AWS account owner):
#   - Launch a t2.micro EC2 instance (Amazon Linux 2023 AMI, free tier)
#   - Attach an Elastic IP so the URL stays stable across restarts
#   - Download the .pem key pair, chmod 400 it, set EC2_KEY_FILE in .env
#
# Run from the repo root:
#   ./scripts/setup.sh
#
# Enable OpenShell sandboxing on EC2 (requires kernel 6.2+ — update your AMI first):
#   ./scripts/setup.sh --with-openshell
#
# Rotate Nebius API key (when someone's credits run out):
#   ./scripts/setup.sh --rotate-key
#
# Deploy the public, judge-facing demo (fake data, no bank intake):
#   ./scripts/setup.sh --demo                   # plain docker compose (hermes only)
#   ./scripts/setup.sh --demo --with-openshell  # hermes sandboxed in OpenShell (matches prod)
#   - Runs hermes only (it runs its own Telegram gateway, so /start works without the
#     forwarder/sms-listener); --with-openshell runs it inside the sandbox
#   - Skips the IMAP/bank-email requirement
#   - Opens TELEGRAM_ALLOWED_USERS=* so judges can message the bot. Set
#     DEMO_ALLOWED_USERS in .env.demo to scope access to specific chat IDs.
#   - Seeds 3 months of fake transactions (seed_demo.sh, or sandbox exec under OpenShell)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"
REMOTE_DIR="/home/ec2-user/hushmoney"
REPO_URL="https://github.com/AlejandroBlanco2001/Untyped.git"

# ── Colors ─────────────────────────────────────────────────────────────────────

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[setup]${NC} $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC}  $*"; }
error() { echo -e "${RED}[error]${NC} $*" >&2; exit 1; }

# ── Helpers ────────────────────────────────────────────────────────────────────

require() {
    command -v "$1" &>/dev/null || error "'$1' not found. Install it first: $2"
}

env_var() {
    # `|| true` so a key that is absent (e.g. IMAP_* / TELEGRAM_API_* in .env.demo)
    # does not make grep return non-zero and trip `set -o pipefail` + `set -e`.
    { grep -E "^$1=" "$ENV_FILE" || true; } | head -n1 | cut -d= -f2- | tr -d '"' | tr -d "'"
}

ssh_ec2() {
    ssh -i "$EC2_KEY_FILE" -o StrictHostKeyChecking=no "$EC2_USER@$EC2_HOST" "$@"
}

# ── Argument parsing ───────────────────────────────────────────────────────────

ROTATE_KEY=false
WITH_OPENSHELL=false
DEMO=false
for arg in "$@"; do
    case $arg in
        --rotate-key)     ROTATE_KEY=true ;;
        --with-openshell) WITH_OPENSHELL=true ;;
        --demo)           DEMO=true ;;
        *) error "Unknown argument: $arg" ;;
    esac
done

# Demo reads its own gitignored env file so it never clobbers your real .env.
if [[ "$DEMO" == true ]]; then
    ENV_FILE="$REPO_ROOT/.env.demo"
fi

# ── Step 1: Check tools ────────────────────────────────────────────────────────

info "Checking required tools..."
require ssh "should be pre-installed on your OS"
info "All tools present."

# ── Step 2: .env ───────────────────────────────────────────────────────────────

if [[ ! -f "$ENV_FILE" ]]; then
    cp "$REPO_ROOT/.env.example" "$ENV_FILE"
    warn "$(basename "$ENV_FILE") created from .env.example — fill in your secrets, then re-run."
    exit 0
fi

NEBIUS_API_KEY="$(env_var NEBIUS_API_KEY)"
TELEGRAM_BOT_TOKEN="$(env_var TELEGRAM_BOT_TOKEN)"
TELEGRAM_CHAT_ID="$(env_var TELEGRAM_CHAT_ID)"
HERMES_GATEWAY_SECRET="$(env_var HERMES_GATEWAY_SECRET)"
EC2_HOST="$(env_var EC2_HOST)"
EC2_USER="$(env_var EC2_USER)"
EC2_KEY_FILE="$(eval echo "$(env_var EC2_KEY_FILE)")"  # expand ~ if present
IMAP_HOST="$(env_var IMAP_HOST)"
IMAP_USERNAME="$(env_var IMAP_USERNAME)"
IMAP_PASSWORD="$(env_var IMAP_PASSWORD)"
BANK_SENDER_EMAILS="$(env_var BANK_SENDER_EMAILS)"
TELEGRAM_API_ID="$(env_var TELEGRAM_API_ID)"
TELEGRAM_API_HASH="$(env_var TELEGRAM_API_HASH)"
TELEGRAM_SESSION_STRING="$(env_var TELEGRAM_SESSION_STRING)"
TELEGRAM_WEBHOOK_SECRET="$(env_var TELEGRAM_WEBHOOK_SECRET)"
BOT_USERNAME="$(env_var BOT_USERNAME)"
DEMO_ALLOWED_USERS="$(env_var DEMO_ALLOWED_USERS)"

[[ -z "$NEBIUS_API_KEY"     || "$NEBIUS_API_KEY"     == *"your-"* ]] && error "NEBIUS_API_KEY not set in .env"
[[ -z "$TELEGRAM_BOT_TOKEN" || "$TELEGRAM_BOT_TOKEN" == *"your-"* ]] && error "TELEGRAM_BOT_TOKEN not set in .env"
[[ -z "$TELEGRAM_CHAT_ID"   || "$TELEGRAM_CHAT_ID"   == *"your-"* ]] && error "TELEGRAM_CHAT_ID not set in .env"
[[ -z "$EC2_HOST"           || "$EC2_HOST"           == *"your-"* ]] && error "EC2_HOST not set in .env"
if [[ "$DEMO" == false ]]; then
    [[ -z "$IMAP_HOST"          ]] && error "IMAP_HOST not set in .env"
    [[ -z "$IMAP_USERNAME"      ]] && error "IMAP_USERNAME not set in .env"
    [[ -z "$IMAP_PASSWORD"      ]] && error "IMAP_PASSWORD not set in .env"
    [[ -z "$BANK_SENDER_EMAILS" ]] && error "BANK_SENDER_EMAILS not set in .env"
fi
[[ ! -f "$EC2_KEY_FILE"     ]] && error "EC2_KEY_FILE '$EC2_KEY_FILE' not found"

EC2_USER="${EC2_USER:-ec2-user}"
info ".env looks good."

# ── Access list + services to run (demo vs normal) ───────────────────────────
# Compose reads TELEGRAM_ALLOWED_USERS and falls back to TELEGRAM_CHAT_ID.
if [[ "$DEMO" == true ]]; then
    SERVICES="hermes"   # hermes runs its own Telegram gateway; no bank intake for the demo
    if [[ -n "$DEMO_ALLOWED_USERS" ]]; then
        ALLOWED_USERS="$DEMO_ALLOWED_USERS"
    else
        # Hermes treats an EMPTY allowlist as deny-all; "*" is the documented open-access
        # wildcard (gateway/authz_mixin.py). Open it so judges can message without pre-sharing IDs.
        ALLOWED_USERS="*"
        warn "Demo mode: TELEGRAM_ALLOWED_USERS=* (open to ANY Telegram user) so judges can reach"
        warn "the bot. This can invite spam / Nebius credit burn — set DEMO_ALLOWED_USERS in"
        warn ".env.demo to scope it to specific chat IDs if you prefer."
    fi
else
    ALLOWED_USERS="$TELEGRAM_CHAT_ID"
    if [[ -n "$TELEGRAM_API_ID" && "$TELEGRAM_API_ID" != *"your-"* ]]; then
        SERVICES="hermes forwarder sms-listener"
    else
        SERVICES="hermes forwarder"
        warn "TELEGRAM_API_ID not set — skipping sms-listener (SMS capture disabled)."
    fi
fi

# ── Step 3: Bootstrap EC2 (first run only) ────────────────────────────────────

if [[ "$ROTATE_KEY" == false ]]; then
    info "Checking EC2 instance at $EC2_HOST..."

    if ! ssh_ec2 "command -v docker &>/dev/null"; then
        info "Installing Docker on EC2..."
        ssh_ec2 "sudo dnf update -y && sudo dnf install -y docker git && sudo systemctl enable --now docker && sudo usermod -aG docker ec2-user"
        warn "Docker installed. You may need to re-run this script once (group membership refreshes on new shell)."
    fi

    if ! ssh_ec2 "docker compose version &>/dev/null 2>&1"; then
        info "Installing Docker Compose v2 plugin on EC2..."
        # docker-compose-plugin is not in AL2023 repos; install the CLI plugin binary directly.
        ssh_ec2 "sudo mkdir -p /usr/local/lib/docker/cli-plugins && sudo curl -fsSL https://github.com/docker/compose/releases/download/v2.27.1/docker-compose-linux-x86_64 -o /usr/local/lib/docker/cli-plugins/docker-compose && sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose"
    fi

    if ! ssh_ec2 "test -d $REMOTE_DIR"; then
        info "Cloning repo to EC2..."
        ssh_ec2 "git clone $REPO_URL $REMOTE_DIR"
    else
        info "Pulling latest code on EC2..."
        ssh_ec2 "cd $REMOTE_DIR && git pull"
    fi
fi

# ── Step 4: Push secrets + start stack ────────────────────────────────────────

info "Writing .env to EC2..."
ssh_ec2 "cat > $REMOTE_DIR/.env" <<EOF
NEBIUS_API_KEY=$NEBIUS_API_KEY
TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID=$TELEGRAM_CHAT_ID
TELEGRAM_ALLOWED_USERS=$ALLOWED_USERS
BOT_USERNAME=$BOT_USERNAME
HERMES_GATEWAY_SECRET=${HERMES_GATEWAY_SECRET:-}
HERMES_GATEWAY_URL=http://hermes:8080/gateway
HERMES_UID=1000
HERMES_GID=1000
IMAP_HOST=$IMAP_HOST
IMAP_USERNAME=$IMAP_USERNAME
IMAP_PASSWORD=$IMAP_PASSWORD
BANK_SENDER_EMAILS=$BANK_SENDER_EMAILS
POLL_INTERVAL_SECONDS=${POLL_INTERVAL_SECONDS:-300}
TELEGRAM_API_ID=$TELEGRAM_API_ID
TELEGRAM_API_HASH=$TELEGRAM_API_HASH
TELEGRAM_SESSION_STRING=$TELEGRAM_SESSION_STRING
TELEGRAM_WEBHOOK_SECRET=${TELEGRAM_WEBHOOK_SECRET:-}
EOF

# docker-compose.yml declares its volumes as `external: true`, so compose never
# creates them and fails if they are missing. `docker volume create` is idempotent.
info "Ensuring external Docker volumes exist on EC2..."
ssh_ec2 "for v in untyped_hermes-data untyped_forwarder-data untyped_pattern-inbox; do docker volume create \$v >/dev/null; done"

if [[ "$WITH_OPENSHELL" == true ]]; then
    # ── OpenShell path ─────────────────────────────────────────────────────────
    # Requires kernel 6.2+ on EC2. Check first — AL2023 default ships 6.1.
    EC2_KERNEL="$(ssh_ec2 "uname -r")"
    # Compare major/minor as integers — a float test wrongly ranks 6.18 below 6.2.
    EC2_MAJOR=$((10#$(echo "$EC2_KERNEL" | cut -d. -f1)))
    EC2_MINOR=$((10#$(echo "$EC2_KERNEL" | cut -d. -f2)))
    if (( EC2_MAJOR < 6 || (EC2_MAJOR == 6 && EC2_MINOR < 2) )); then
        error "EC2 kernel $EC2_KERNEL is below 6.2 — OpenShell requires 6.2+.
  Update your AMI: launch a new AL2023 instance (kernel 6.6+) or switch to Ubuntu 24.04,
  then update EC2_HOST in .env and re-run setup.sh."
    fi

    # AL2023 provides Docker but NOT podman (only containers-common libs), yet
    # OpenShell's Fedora RPM hard-requires podman. OpenShell runs fine on Docker,
    # so patch the installer's one package step (dnf install) to `rpm --nodeps`,
    # skipping the unsatisfiable podman dependency. The installer then auto-starts
    # the gateway with the default (podman) config and fails — expected; we flip
    # the driver to Docker next, so tolerate that non-zero exit.
    info "Installing OpenShell on EC2 (Docker runtime; podman RPM dep bypassed)..."
    ssh_ec2 'command -v openshell >/dev/null 2>&1 || {
        curl -fsSL https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh -o /tmp/openshell-install.sh &&
        sed -i "s/as_root dnf install -y /as_root rpm -Uvh --replacepkgs --nodeps /" /tmp/openshell-install.sh &&
        { sh /tmp/openshell-install.sh || true; }
    }'
    ssh_ec2 "command -v openshell >/dev/null 2>&1" || error "OpenShell CLI did not install on EC2."

    # The default gateway config pins compute_driver="podman" (absent on AL2023).
    # Derive from the installed default and flip it to Docker, then (re)start.
    info "Pointing the OpenShell gateway at Docker on EC2..."
    ssh_ec2 'mkdir -p ~/.config/openshell &&
        cp /usr/share/openshell-gateway/gateway.toml.default ~/.config/openshell/gateway.toml &&
        sed -i "s/^compute_driver = \"podman\"/compute_driver = \"docker\"/" ~/.config/openshell/gateway.toml &&
        systemctl --user restart openshell-gateway'
    info "Waiting for the gateway to become active..."
    ssh_ec2 'for i in $(seq 1 30); do systemctl --user is-active --quiet openshell-gateway && exit 0; sleep 2; done;
        echo "gateway did not become active:"; systemctl --user status openshell-gateway --no-pager | head -25; exit 1'

    # Inference: hermes calls Nebius directly from inside the sandbox (egress is
    # allowed in policy.yaml). OpenShell's own inference.local routing needs a
    # provider "profile" unavailable for the openai type on this build, so we skip
    # it — the sandbox still enforces filesystem/syscall/network isolation.
    #
    # Sandbox env — hermes sources /app/.env on start.
    info "Preparing sandbox environment file..."
    ssh_ec2 "cat > /tmp/hermes-sandbox.env" <<EOF
OPENAI_BASE_URL=https://api.studio.nebius.ai/v1/
OPENAI_API_KEY=$NEBIUS_API_KEY
TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID=$TELEGRAM_CHAT_ID
TELEGRAM_ALLOWED_USERS=$ALLOWED_USERS
HERMES_GATEWAY_SECRET=${HERMES_GATEWAY_SECRET:-}
HUSHMONEY_DB=/opt/data/hushmoney.db
HUSHMONEY_INBOX=/opt/data/pattern-inbox
HUSHMONEY_REGISTRY=/opt/data/pattern-inbox/registry.json
EOF

    # Create the sandbox: build the self-contained image from the repo Dockerfile,
    # apply the policy, upload the env. In v0.1.5 `--upload` is mutually exclusive
    # with a trailing `-- command`, so we omit the command and rely on the image's
    # ENTRYPOINT (/app/docker-entrypoint.sh). The entrypoint is a long-lived
    # service, so run create detached and poll for readiness.
    info "Creating the OpenShell sandbox (builds image, applies policy)..."
    ssh_ec2 "openshell sandbox delete hushmoney-1 2>/dev/null || true"
    ssh_ec2 "cd $REMOTE_DIR && nohup openshell sandbox create \
        --name hushmoney-1 \
        --from . \
        --policy config/openshell/policy.yaml \
        --no-auto-providers \
        --upload /tmp/hermes-sandbox.env:/app/.env \
        --no-tty > /tmp/hushmoney-sandbox.log 2>&1 &"

    info "Waiting for the sandbox to become reachable (image build can take a few minutes)..."
    ssh_ec2 'for i in $(seq 1 90); do openshell sandbox exec -n hushmoney-1 -- true 2>/dev/null && exit 0; sleep 5; done;
        echo "sandbox not reachable; recent build/run log:"; tail -40 /tmp/hushmoney-sandbox.log 2>/dev/null; exit 1'

    if [[ "$DEMO" == false ]]; then
        info "Starting forwarder on EC2..."
        ssh_ec2 "cd $REMOTE_DIR && docker compose up -d forwarder"
    else
        info "Seeding demo data into the sandbox..."
        # No `hermes` container under OpenShell — seed via `sandbox exec`. seed_demo.py
        # is self-contained (stdlib sqlite3, applies its own schema).
        ssh_ec2 "
            openshell sandbox upload hushmoney-1 $REMOTE_DIR/scripts/seed_demo.py /tmp/seed_demo.py
            openshell sandbox upload hushmoney-1 $REMOTE_DIR/config/schema.sql   /tmp/schema.sql
            openshell sandbox exec -n hushmoney-1 -- sh -c 'HUSHMONEY_DB=/opt/data/hushmoney.db HUSHMONEY_SCHEMA=/tmp/schema.sql python3 /tmp/seed_demo.py'
        " || warn "Demo seeding failed. Re-run the upload+exec, or let the setup wizard collect accounts live in Telegram."
    fi
else
    # ── Standard path (no OpenShell) ───────────────────────────────────────────
    info "Starting stack on EC2 (services: $SERVICES)..."
    ssh_ec2 "cd $REMOTE_DIR && docker compose pull $SERVICES 2>/dev/null; docker compose up -d --build $SERVICES"

    if [[ "$DEMO" == true ]]; then
        info "Waiting for hermes to come up, then seeding demo data..."
        ssh_ec2 "sleep 15 && cd $REMOTE_DIR && ./scripts/seed_demo.sh" \
            || warn "Seeding failed (hermes may still be starting). Re-run: ssh -i $EC2_KEY_FILE $EC2_USER@$EC2_HOST 'cd $REMOTE_DIR && ./scripts/seed_demo.sh'"
    fi
fi

# ── Done ───────────────────────────────────────────────────────────────────────

echo ""
if [[ "$ROTATE_KEY" == true ]]; then
    info "Key rotation complete. Stack restarted with new NEBIUS_API_KEY."
else
    info "Setup complete."
    echo ""
    echo "  EC2 instance:  $EC2_USER@$EC2_HOST"
    echo "  Stack logs:    ssh -i $EC2_KEY_FILE $EC2_USER@$EC2_HOST 'cd $REMOTE_DIR && docker compose logs -f'"
    echo "  Redeploy:      ssh -i $EC2_KEY_FILE $EC2_USER@$EC2_HOST 'cd $REMOTE_DIR && git pull && docker compose up -d --build'"
    echo "  Local dev:     ./scripts/dev.sh"
    echo ""
    if [[ "$DEMO" == true ]]; then
        echo "  DEMO deployed:"
        echo "    Bot:         open Telegram and send /start to ${BOT_USERNAME:-your demo bot}"
        echo "    Data:        3 months of fake transactions seeded (seed_demo.sh is re-runnable)"
        echo "    Access:      TELEGRAM_ALLOWED_USERS=${ALLOWED_USERS:-<empty = all>}"
        echo "    Keep alive:  leave this instance up through the judging period."
        echo ""
    fi
fi
