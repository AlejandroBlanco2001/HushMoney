# HushMoney

> Zero-input expense tracking. Your bank tells us; you just check your summary.

HushMoney intercepts financial notifications from email, SMS, and messaging apps, strips all sensitive details, and hands clean transaction signals to an AI agent that tracks, categorizes, and summarizes your spending — automatically.

## How It Works

```
Bank email / SMS / Telegram
        │
        ▼
  ┌─────────────┐
  │  Forwarder  │  strips OTPs, account numbers, PII
  └──────┬──────┘
         │ clean payload (amount, merchant, date, type)
         ▼
  ┌─────────────┐
  │    Hermes   │  AI agent — categorizes, stores, reasons
  │    Agent    │
  └──────┬──────┘
         │
    ┌────┴────┐
    │  SQLite │  persistent memory
    └─────────┘
         │
         ▼
  Telegram reminder  (cash operations only)
```

## Features

- **Automatic expense capture** from bank notifications — no manual entry
- **Smart categorization** — groceries, transport, dining, subscriptions, etc.
- **Debt tracking** — keep a list of who owes you and who you owe
- **Transaction descriptions** — Hermes infers context from the merchant name
- **Summaries** — daily, weekly, and monthly rolled up and delivered to you

## Tech Stack

| Layer | Technology |
|---|---|
| AI Agent | [Hermes Agent](https://github.com/NousResearch/hermes-agent) — NousResearch |
| Agent Sandbox | NVIDIA OpenShell |
| Models | NVIDIA open models |
| Infra | Nebius AI Cloud |
| Forwarder | Python 3.12 |
| Database | SQLite |
| Notifications | Telegram Bot API |

## Repository Structure

```
hushmoney/
├── AGENTS.md        # AI assistant rules and routing table
├── forwarder/       # Sanitization service (Python 3.12)
├── skills/          # Custom Hermes skills
│   ├── expense_tracker/
│   ├── categorizer/
│   ├── debt_tracker/
│   └── summaries/
├── config/          # Hermes config, OpenShell policy, prompts
└── docs/            # Architecture, rules, onboarding
```

## Getting Started

> **Not a developer?** Read `docs/onboarding.md` — it walks you through making changes with Cursor or OpenCode without writing code from scratch.

### Prerequisites

- Python 3.12+
- A running Hermes Agent instance (see [Hermes setup](https://github.com/NousResearch/hermes-agent))
- NVIDIA OpenShell (for sandboxed agent execution)
- Nebius API credentials
- A Telegram bot token (for cash operation reminders)

### Setup

Configuration and setup steps will be added as each component is built. Check `docs/architecture.md` for the full integration picture.

## Security

HushMoney is designed with a hard privacy boundary at the forwarder. Raw financial notifications — including OTPs, full account numbers, and recipient names — never reach the agent or the database. See `docs/rules/security.md` for the full policy.

## License

MIT
