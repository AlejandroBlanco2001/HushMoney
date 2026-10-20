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
# Rotate Nebius API key (when someone's credits run out):
#   ./scripts/setup.sh --rotate-key

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
    grep -E "^$1=" "$ENV_FILE" | cut -d= -f2- | tr -d '"' | tr -d "'"
}

ssh_ec2() {
    ssh -i "$EC2_KEY_FILE" -o StrictHostKeyChecking=no "$EC2_USER@$EC2_HOST" "$@"
}

# ── Argument parsing ───────────────────────────────────────────────────────────

ROTATE_KEY=false
for arg in "$@"; do
    case $arg in
        --rotate-key) ROTATE_KEY=true ;;
        *) error "Unknown argument: $arg" ;;
    esac
done

# ── Step 1: Check tools ────────────────────────────────────────────────────────

info "Checking required tools..."
require ssh "should be pre-installed on your OS"
info "All tools present."

# ── Step 2: .env ───────────────────────────────────────────────────────────────

if [[ ! -f "$ENV_FILE" ]]; then
    cp "$REPO_ROOT/.env.example" "$ENV_FILE"
    warn ".env created from .env.example — fill in your secrets, then re-run."
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

[[ -z "$NEBIUS_API_KEY"     || "$NEBIUS_API_KEY"     == *"your-"* ]] && error "NEBIUS_API_KEY not set in .env"
[[ -z "$TELEGRAM_BOT_TOKEN" || "$TELEGRAM_BOT_TOKEN" == *"your-"* ]] && error "TELEGRAM_BOT_TOKEN not set in .env"
[[ -z "$TELEGRAM_CHAT_ID"   || "$TELEGRAM_CHAT_ID"   == *"your-"* ]] && error "TELEGRAM_CHAT_ID not set in .env"
[[ -z "$EC2_HOST"           || "$EC2_HOST"           == *"your-"* ]] && error "EC2_HOST not set in .env"
[[ -z "$IMAP_HOST"          ]] && error "IMAP_HOST not set in .env"
[[ -z "$IMAP_USERNAME"      ]] && error "IMAP_USERNAME not set in .env"
[[ -z "$IMAP_PASSWORD"      ]] && error "IMAP_PASSWORD not set in .env"
[[ -z "$BANK_SENDER_EMAILS" ]] && error "BANK_SENDER_EMAILS not set in .env"
[[ ! -f "$EC2_KEY_FILE"     ]] && error "EC2_KEY_FILE '$EC2_KEY_FILE' not found"

EC2_USER="${EC2_USER:-ec2-user}"
info ".env looks good."

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
HERMES_GATEWAY_SECRET=${HERMES_GATEWAY_SECRET:-}
HERMES_GATEWAY_URL=http://hermes:8080/gateway
HERMES_UID=1000
HERMES_GID=1000
IMAP_HOST=$IMAP_HOST
IMAP_USERNAME=$IMAP_USERNAME
IMAP_PASSWORD=$IMAP_PASSWORD
BANK_SENDER_EMAILS=$BANK_SENDER_EMAILS
POLL_INTERVAL_SECONDS=${POLL_INTERVAL_SECONDS:-300}
EOF

info "Starting stack on EC2..."
ssh_ec2 "cd $REMOTE_DIR && docker compose pull 2>/dev/null; docker compose up -d --build"

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
    echo "  Local dev:     HERMES_UID=\$(id -u) HERMES_GID=\$(id -g) docker compose up"
    echo ""
fi
