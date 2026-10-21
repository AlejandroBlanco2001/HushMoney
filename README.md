# HushMoney

> Zero-input expense tracking. Your bank tells us; you just check your summary.

HushMoney intercepts financial notifications from email and SMS, strips all sensitive details, and hands clean transaction signals to an AI agent that tracks, categorizes, and summarizes your spending — automatically.

## How It Works

```
Bank email notification          Bank SMS (iPhone → Saved Messages)
        │                                    │
        ▼                                    ▼
  Gmail inbox                     Pyrogram listener
  (IMAP polling)                  (watches your Saved Messages,
        │                          forwards to your bot as you)
        └──────────────┬───────────────────┘
                       │
                       ▼
             ┌─────────────────┐
             │    Forwarder    │  strips OTPs, account numbers, PII
             └────────┬────────┘
                      │ clean payload (amount, merchant, date, type)
                      ▼
             ┌─────────────────┐
             │  Hermes Agent   │  AI agent — categorizes, stores, reasons
             │  (OpenShell)    │
             └────────┬────────┘
                      │
                 ┌────┴────┐
                 │ SQLite  │  persistent memory
                 └─────────┘
                      │
                      ▼
             Telegram summary / reminder
```

## Features

- **Automatic expense capture** from bank emails and SMS — no manual entry
- **iPhone SMS forwarding** — send bank SMS to Saved Messages; the listener picks it up automatically
- **Smart categorization** — groceries, transport, dining, subscriptions, etc.
- **Debt tracking** — keep a list of who owes you and who you owe
- **Transaction descriptions** — Hermes infers context from the merchant name
- **Summaries** — daily, weekly, and monthly rolled up and delivered to you
- **Bank learning** — teach Hermes new bank formats interactively via Telegram

## Tech Stack

| Layer | Technology |
|---|---|
| AI Agent | [Hermes Agent](https://github.com/NousResearch/hermes-agent) — NousResearch |
| Agent Sandbox | NVIDIA OpenShell |
| Models | NVIDIA open models via Nebius Serverless |
| SMS listener | Pyrogram (MTProto user client) |
| Forwarder | Python 3.12 |
| Database | SQLite |
| Notifications | Telegram Bot API |

## Repository Structure

```
hushmoney/
├── AGENTS.md              # AI assistant rules, routing table, product direction
├── forwarder/             # Sanitization service (Python 3.12)
│   └── src/forwarder/
│       ├── channels/      # telegram.py — bot webhook handler
│       ├── sanitizer/     # strips PII, extracts CleanPayload
│       ├── imap.py        # Gmail IMAP polling
│       └── hermes.py      # dispatches to gateway_server
├── scripts/
│   ├── dev.sh             # local dev launcher (handles OpenShell + session setup)
│   ├── sms_listener.py    # Pyrogram listener — Saved Messages → bot
│   └── gen_session.py     # one-time Telegram session generator (called by dev.sh)
├── skills/                # Custom Hermes skills
│   ├── expense_tracker/
│   ├── categorizer/
│   ├── debt_tracker/
│   ├── summaries/
│   └── bank_learning/
├── config/                # Hermes config, OpenShell policy, prompts
└── docs/                  # Architecture, rules, onboarding
```

## Getting Started

### Prerequisites

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- [Podman](https://podman.io/) (or Docker)
- A Telegram bot token — create one via [@BotFather](https://t.me/BotFather)
- Telegram API credentials — get them at [my.telegram.org](https://my.telegram.org)
- Nebius API key — [nebius.ai](https://nebius.ai)
- Gmail App Password — [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)

### Setup

```bash
git clone https://github.com/your-org/hushmoney
cd hushmoney
cp .env.example .env
$EDITOR .env   # fill in your tokens and credentials
```

Then start the full stack:

```bash
./scripts/dev.sh
```

On first run, `dev.sh` will:
1. Detect the missing `TELEGRAM_SESSION_STRING`
2. Prompt you for your phone number and a Telegram OTP (one-time only)
3. Save the session string to `.env` automatically
4. Start Hermes inside an OpenShell sandbox and the forwarder via Podman

**No OpenShell?** Run without the sandbox:

```bash
./scripts/dev.sh --no-openshell
```

### iPhone SMS Forwarding

In the Shortcuts app, create an automation that triggers when a message arrives from your bank:

1. Action: **Send Message** → recipient: **yourself** (Saved Messages)
2. Message body: the SMS text from the trigger

The Pyrogram listener (`scripts/sms_listener.py`) watches your Saved Messages 24/7 and forwards matching messages to your bot automatically.

For more detail, see [docs/architecture.md](docs/architecture.md).

## Security

HushMoney is designed with a hard privacy boundary at the forwarder. Raw financial notifications — including OTPs, full account numbers, and recipient names — never reach the agent or the database. See `docs/rules/security.md` for the full policy.

## License

MIT
