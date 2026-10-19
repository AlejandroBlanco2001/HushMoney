# Deployment Guide

HushMoney runs on a single AWS EC2 t2.micro instance (free tier). One instance serves the whole team — everyone points their Cloudflare Worker and local dev at it.

## Architecture recap

```
Bank email → Cloudflare Worker → EC2 (Forwarder + Hermes) → Telegram
Bank SMS   → Telegram Bot      ↗
```

- **Cloudflare Email Worker** — serverless, always-on, no management needed
- **EC2 t2.micro** — runs Forwarder + Hermes Agent via Docker Compose
- **Nebius Serverless** — LLM inference (NVIDIA Nemotron 3 Nano), called by Hermes

## First-time setup (AWS account owner)

These steps are done once by whoever owns the AWS account. Skip to [Team setup](#team-setup) if the instance is already running.

### 1. Launch the EC2 instance

1. Open the [AWS EC2 console](https://console.aws.amazon.com/ec2/)
2. Launch instance → **Amazon Linux 2023 AMI** (free tier eligible)
3. Instance type: **t2.micro**
4. Key pair: create a new one (`hushmoney`), download the `.pem` file
5. Security group — add inbound rules:
   - SSH (port 22) — your IP only
   - Custom TCP (port 9000) — 0.0.0.0/0 (forwarder webhook, needed by Cloudflare)
6. Launch

### 2. Attach an Elastic IP

Without an Elastic IP the public IP changes every time the instance restarts, which breaks the Cloudflare Worker's webhook URL.

1. EC2 console → **Elastic IPs** → Allocate Elastic IP address
2. Actions → **Associate** → select your instance
3. Note the Elastic IP — this is your `EC2_HOST`

### 3. Set file permissions on the key

```sh
chmod 400 ~/.ssh/hushmoney.pem
```

## Team setup

Every team member runs this once to get their local environment connected to the shared EC2 instance.

### Prerequisites

- [wrangler](https://developers.cloudflare.com/workers/wrangler/install-and-update/) — `npm install -g wrangler`
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
| `EMAIL_WEBHOOK_SECRET` | Generate: `openssl rand -hex 32` |
| `HERMES_GATEWAY_SECRET` | Generate: `openssl rand -hex 32` |
| `EC2_HOST` | Elastic IP from the AWS console |
| `EC2_KEY_FILE` | Path to `hushmoney.pem` on your machine |

```sh
# 3. Run setup
./scripts/setup.sh
```

The script will:
- Deploy the Cloudflare Email Worker
- Bootstrap Docker on the EC2 instance (first run only)
- Push secrets to the instance
- Start Hermes Agent via Docker Compose
- Wire the Cloudflare Worker's webhook URL to the EC2 instance

## Local development

```sh
HERMES_UID=$(id -u) HERMES_GID=$(id -g) docker compose up
```

This starts Hermes Agent locally with the skills and config from the repo mounted read-only. SQLite data persists in the `hermes-data` Docker volume.

To rebuild after a Dockerfile change:

```sh
docker compose up --build
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

# Tail Cloudflare Worker logs
cd config/cloudflare && npx wrangler tail
```

## Troubleshooting

**`Permission denied (publickey)` when SSHing**
- Check the key path in `EC2_KEY_FILE` is correct
- Confirm `chmod 400` was applied to the `.pem` file
- Confirm the EC2 security group allows inbound SSH from your current IP

**Cloudflare Worker can't reach the forwarder**
- Check the EC2 security group has port 9000 open to `0.0.0.0/0`
- Confirm the Elastic IP is attached (EC2 console → Instances → check Public IPv4)
- Check `wrangler.toml` has the correct `EMAIL_WEBHOOK_URL`

**Docker Compose won't start on EC2**
- SSH into the instance and run `docker compose logs` to see what failed
- If it's a secret missing, re-run `./scripts/setup.sh --rotate-key` after fixing `.env`
