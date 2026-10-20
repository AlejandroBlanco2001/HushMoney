# Deployment Guide

HushMoney runs on a single AWS EC2 t2.micro instance (free tier). The forwarder polls your Gmail inbox directly — no domain, no Cloudflare account, no webhook setup required.

## Architecture recap

```
Bank email → Gmail inbox → Forwarder (IMAP poll every 5 min) → Hermes → Telegram
Bank SMS   → Telegram Bot ──────────────────────────────────────────────↗
```

- **EC2 t2.micro** — runs Forwarder + Hermes Agent via Docker Compose
- **Gmail IMAP** — Forwarder polls for unread emails from your bank's sender address
- **Nebius Serverless** — LLM inference (NVIDIA Nemotron Nano), called by Hermes

## First-time setup (AWS account owner)

These steps are done once by whoever owns the AWS account.

### 1. Launch the EC2 instance

1. Open the [AWS EC2 console](https://console.aws.amazon.com/ec2/)
2. Launch instance → **Amazon Linux 2023 AMI** (free tier eligible)
3. Instance type: **t2.micro**
4. Key pair: create a new one (`hushmoney`), download the `.pem` file
5. Security group — add inbound rules:
   - SSH (port 22) — your IP only
6. Launch

### 2. Attach an Elastic IP

Without an Elastic IP the public IP changes every time the instance restarts.

1. EC2 console → **Elastic IPs** → Allocate Elastic IP address
2. Actions → **Associate** → select your instance
3. Note the Elastic IP — this is your `EC2_HOST`

### 3. Set file permissions on the key

```sh
chmod 400 ~/.ssh/hushmoney.pem
```

### 4. Set up Gmail App Password

The forwarder authenticates to Gmail using an App Password (regular passwords are blocked by Google for IMAP).

1. Enable IMAP: Gmail Settings → See all settings → **Forwarding and POP/IMAP** → Enable IMAP
2. Generate App Password: [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) → name it "hushmoney" → copy the 16-character password

> **Outlook users:** set up a forwarding rule in Outlook to forward bank emails to your Gmail, then use your Gmail address and App Password here. Set `BANK_SENDER_EMAILS` to your Outlook address (that's who Gmail will see as the sender).

## Team setup

Every team member runs this once to get their local environment connected.

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) — for local development
- The `.pem` key file — get it from the team shared folder (never commit it)
- A [Nebius](https://nebius.com) account with Token Factory credits

### Steps

```sh
# 1. Clone the repo
git clone https://github.com/AlejandroBlanco2001/Untyped.git
cd Untyped

# 2. Copy .env and fill in your values
cp .env.example .env
$EDITOR .env
```

Fill in these values in `.env`:

| Variable | Where to get it |
|---|---|
| `NEBIUS_API_KEY` | [Nebius console](https://studio.nebius.com) → API Keys |
| `TELEGRAM_BOT_TOKEN` | Create a bot via [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_ID` | Send `/start` to [@userinfobot](https://t.me/userinfobot) |
| `IMAP_HOST` | `imap.gmail.com` (or your provider) |
| `IMAP_USERNAME` | Your full Gmail address |
| `IMAP_PASSWORD` | 16-char App Password from Google |
| `BANK_SENDER_EMAILS` | Comma-separated sender addresses from your bank |
| `EC2_HOST` | Elastic IP from AWS console |
| `EC2_KEY_FILE` | Path to `hushmoney.pem` on your machine |

```sh
# 3. Run setup
./scripts/setup.sh
```

The script will:
- Bootstrap Docker on the EC2 instance (first run only)
- Push secrets to the instance
- Start Hermes Agent + Forwarder via Docker Compose

## Local development

```sh
HERMES_UID=$(id -u) HERMES_GID=$(id -g) docker compose up
```

This starts Hermes Agent and the Forwarder locally. SQLite data persists in the `hermes-data` Docker volume.

To rebuild after a Dockerfile change:

```sh
docker compose up --build
```

To run the forwarder in dry-run mode (logs emails, skips Hermes dispatch):

```sh
set -a && source .env && set +a && DRY_RUN=true uv run python -m forwarder
```

## Rotating Nebius API keys

Each team member has $25 in Token Factory credits. When someone's key runs out:

1. The next person updates `NEBIUS_API_KEY` in their `.env`
2. Run:
   ```sh
   ./scripts/setup.sh --rotate-key
   ```

This re-writes the `.env` on EC2 and restarts the stack. Takes ~10 seconds.

## Useful commands

```sh
# Tail logs on EC2
ssh -i ~/.ssh/hushmoney.pem ec2-user@<EC2_HOST> \
  'cd hushmoney && docker compose logs -f'

# Redeploy after a git push (no secrets change needed)
ssh -i ~/.ssh/hushmoney.pem ec2-user@<EC2_HOST> \
  'cd hushmoney && git pull && docker compose up -d --build'
```

## Troubleshooting

**`Permission denied (publickey)` when SSHing**
- Check the key path in `EC2_KEY_FILE` is correct
- Confirm `chmod 400` was applied to the `.pem` file
- Confirm the EC2 security group allows inbound SSH from your current IP

**Forwarder not picking up emails**
- Check `BANK_SENDER_EMAILS` matches the exact sender address in your bank's emails
- Confirm IMAP is enabled in Gmail settings
- Confirm the App Password is 16 characters with no spaces
- SSH into EC2 and run `docker compose logs forwarder` to see poll results

**Docker Compose won't start on EC2**
- SSH into the instance and run `docker compose logs` to see what failed
- If it's a secret missing, re-run `./scripts/setup.sh --rotate-key` after fixing `.env`
