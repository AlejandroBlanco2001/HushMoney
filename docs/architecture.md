# Architecture

## Deployment Model

HushMoney is a **single-user, self-hosted deployment**. One instance runs on Nebius for one person. There is no multi-tenancy, no shared infrastructure, no centralized service. The user owns the bot token, the email address, the Nebius instance, and the SQLite database. Nothing is shared.

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         Input Sources                           │
│                                                                 │
│   Bank email notification          Bank SMS / Telegram message  │
│          │                                    │                 │
│          ▼                                    ▼                 │
│  Gmail/Outlook forwarding rule      User forwards to their      │
│  → user@hushmoney-deploy.dev        private @TheirOwnBot        │
└────────────┬──────────────────────────────────┬─────────────────┘
             │                                  │
             ▼                                  ▼
   Cloudflare Email Worker              Telegram Bot API
   (inbound email → HTTP POST)          (long-poll or webhook)
             │                                  │
             └──────────────┬───────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                         Forwarder                               │
│                        (Python 3.12)                            │
│                                                                 │
│   channels/email.py          channels/telegram.py               │
│         │                          │                            │
│         └────────────┬─────────────┘                            │
│                      │                                          │
│               sanitizer/                                        │
│          (strip OTP, account #, PII)                            │
│                      │                                          │
│               dispatcher/                                       │
│          (emit clean payload via HTTP)                          │
└──────────────────────┬──────────────────────────────────────────┘
                       │
          { amount, currency, merchant,
            date, transaction_type,
            account_type, channel }
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Hermes Agent                               │
│                                                                 │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │                       skills/                          │   │
│   │  expense_tracker  categorizer  debt_tracker  summaries │   │
│   │  setup  (one-time guided configuration — runs once)    │   │
│   └─────────────────────────────────────────────────────────┘   │
│                            │                                    │
│                       ┌────┴────┐                               │
│                       │ SQLite  │                               │
│                       └─────────┘                               │
│                                                                 │
│   Runtime: NVIDIA OpenShell sandbox                             │
│   Models:  NVIDIA open models via Nebius Serverless             │
└──────────────────────┬──────────────────────────────────────────┘
                       │ (cash operations only)
                       ▼
              User's Telegram bot
              → reminder message
```

## Component Responsibilities

### Cloudflare Email Worker

Receives inbound forwarded emails from the user's email client. Converts the email to an HTTP POST and sends it to the forwarder's email channel endpoint. No credentials stored on the user's side — they configure one forwarding rule in Gmail/Outlook, done.

Configuration lives in `config/cloudflare/`. The worker URL is an env var (`EMAIL_WEBHOOK_URL`).

### Telegram Bot (user-owned)

The user creates their own bot via @BotFather and stores the token in `.env`. The forwarder's Telegram adapter listens for updates on that bot (long-polling or webhook). Only the user's own chat ID can send messages — no public exposure.

The same bot is used for **input** (user forwards bank notifications to it) and **output** (Hermes sends reminders and summaries back through it). Hermes's built-in Telegram gateway handles the output side; the forwarder handles the input side.

### Forwarder (`forwarder/`)

Two channels in, one channel out. Stateless.

| Module | Responsibility |
|---|---|
| `channels/email.py` | Receive HTTP POST from Cloudflare Email Worker |
| `channels/telegram.py` | Receive Telegram bot updates via Bot API |
| `sanitizer/` | Strip OTPs, account numbers, card numbers, PII from raw message |
| `dispatcher/` | POST clean payload to Hermes gateway |

The forwarder holds no state, no database, no retry queue. If dispatch fails, the message is dropped — financial notifications are ephemeral by nature.

**Clean payload schema:**
```json
{
  "amount": 42.50,
  "currency": "USD",
  "merchant": "Starbucks",
  "date": "2026-10-17T09:15:00Z",
  "transaction_type": "debit",
  "account_type": "checking",
  "channel": "email"
}
```

### Hermes Agent + Skills (`skills/`)

| Skill | Responsibility |
|---|---|
| `setup` | One-time guided setup via Telegram — runs once, never again |
| `expense_tracker` | Persist transaction into SQLite, attach description |
| `categorizer` | Classify transaction into a spending category |
| `debt_tracker` | Manage list of people owed / owing |
| `summaries` | Generate daily, weekly, monthly rollups on schedule or on demand |

All skills run inside the NVIDIA OpenShell sandbox. Policy at `config/openshell/policy.yaml`.

### Setup Skill (`skills/setup/`)

Hermes guides the user through one-time configuration via their Telegram bot:

```
User: hermes setup

Hermes: "Let's get HushMoney running. First, create a Telegram bot:
         1. Open @BotFather on Telegram
         2. Send /newbot and follow the prompts
         3. Paste the token here."

User: [pastes token]

Hermes: "Got it. Now your email forwarding address is:
         hushmoney-abc123@your-deploy.dev
         Add a forwarding rule in Gmail:
         Settings → Forwarding → Add forwarding address
         Forward mail from: [your bank's sender address]
         I'll wait for a test email..."

[user configures forwarding, bank sends a test notification]

Hermes: "Received! Setup complete. I'll start tracking from here."
```

After setup completes, the `setup` skill marks itself done and will not re-run unless explicitly reset.

### Config (`config/`)

```
config/
├── hermes.yaml          # Hermes runtime config — no secrets
├── cloudflare/          # Cloudflare Email Worker script and wrangler config
├── openshell/
│   └── policy.yaml      # Sandbox policy — filesystem + network constraints
└── prompts/             # System prompts and skill prompt templates
```

## Data Flow: Happy Path (Email)

1. Bank sends email: `"Debit of USD 42.50 at STARBUCKS — Account ending 1234. OTP: 882910"`
2. Gmail forwarding rule sends it to `hushmoney-abc123@your-deploy.dev`
3. Cloudflare Email Worker receives it, POSTs raw content to forwarder `/channels/email`
4. Forwarder sanitizer strips account suffix and OTP → emits clean payload
5. Dispatcher POSTs clean payload to Hermes gateway
6. Hermes runs `expense_tracker` → stores in SQLite
7. Hermes runs `categorizer` → tags as `dining`
8. No Telegram message sent (digital transaction, fully resolved)

## Data Flow: Cash Operation

1. User's bank sends SMS: `"ATM cash withdrawal USD 100.00 — Account ending 1234"`
2. User forwards the SMS to their Telegram bot (or Android auto-forward app does it)
3. Forwarder Telegram adapter receives the forwarded message
4. Sanitizer strips account suffix → emits clean payload with `transaction_type: cash`
5. Hermes stores the transaction, then sends Telegram reminder:
   `"Cash withdrawal of $100 detected. Add a description? (e.g., groceries, taxi)"`
6. User replies optionally; Hermes updates the record

## Data Flow: Debt Tracking

User tells Hermes directly via Telegram:
`"I paid dinner for João, he owes me $35"`

Hermes runs `debt_tracker` skill → stores entry in SQLite. No forwarder involved.

## Infrastructure

- **Nebius Serverless** hosts Hermes and the forwarder
- **NVIDIA OpenShell** provides the sandboxed agent runtime
- **NVIDIA open models** (via Nebius) handle all LLM inference
- **Cloudflare Email Workers** handles inbound email (free tier, zero server management)
- **SQLite** is local to the Hermes agent's persistent storage volume on Nebius
- The user's Telegram bot is the sole communication channel in both directions

## Privacy Properties

Because this is a single-user self-hosted deployment:

- The Telegram bot token belongs to the user — no third party can read their messages
- The forwarding email address resolves to their Nebius instance — no shared mailbox
- The SQLite database never leaves their Nebius volume
- The OpenShell policy prevents the agent from reaching outside its allowed endpoints
- Raw financial notifications are sanitized before Hermes ever sees them
