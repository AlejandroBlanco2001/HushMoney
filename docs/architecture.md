# Architecture

## Deployment Model

HushMoney is a **single-user, self-hosted deployment**. One instance runs on EC2 for one person. There is no multi-tenancy, no shared infrastructure, no centralized service. The user owns the bot token, the Gmail account, the EC2 instance, and the SQLite database. Nothing is shared.

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         Input Sources                           │
│                                                                 │
│  Bank email notification       Bank SMS (received on iPhone)    │
│          │                                    │                 │
│          ▼                                    ▼                 │
│   Gmail inbox (bank sets       iPhone Shortcut fires:           │
│   up email alerts to Gmail)    sends SMS text to Saved Messages │
└────────────┬──────────────────────────────────┬─────────────────┘
             │                                  │
             ▼                                  ▼
   IMAP Poller (polls Gmail         Pyrogram listener
   every 5 min for unseen           (scripts/sms_listener.py)
   emails from bank senders)        watches Saved Messages via
                                    MTProto, forwards text to bot
             │                                  │
             └──────────────┬───────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                         Forwarder                               │
│                        (Python 3.12)                            │
│                                                                 │
│   imap.py (poll + parse)     channels/telegram.py               │
│         │                          │                            │
│         └────────────┬─────────────┘                            │
│                      │                                          │
│               sanitizer/                                        │
│          (strip OTP, account #, PII)                            │
│                      │                                          │
│               hermes.py                                         │
│          (POST CleanPayload via HTTP)                           │
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

### IMAP Poller (`forwarder/src/forwarder/imap.py`)

Polls the user's Gmail inbox every 5 minutes (configurable via `POLL_INTERVAL_SECONDS`). Connects via IMAP4_SSL using an App Password. For each configured bank sender address, searches for UNSEEN messages, parses them, marks them as seen, and dispatches to Hermes.

Supports auto-forwarded emails: if the email contains `X-Original-From` or `X-Forwarded-From` headers (set by Outlook and other MTAs when forwarding via rules), the original bank sender is recovered from those headers rather than the forwarding address.

No domain, no webhook, no third-party routing service required.

### Telegram (two roles)

**Bot (output + commands):** The user creates a bot via @BotFather and stores the token in `.env`. Hermes uses this bot to send reminders, summaries, and interactive prompts. The forwarder's `channels/telegram.py` receives webhook updates for any direct commands the user sends.

**MTProto user client (SMS input):** `scripts/sms_listener.py` runs a Pyrogram session logged in as the user. It watches Saved Messages (the user's self-chat) for incoming text and forwards it to the bot as a real user message. This is the SMS intake path — iPhone Shortcuts writes to Saved Messages; the listener picks it up.

The session string is generated once by `dev.sh` on first run and stored in `.env`. No session file is needed at runtime.

### Forwarder (`forwarder/`)

Two channels in, one channel out. Stateless.

| Module | Responsibility |
|---|---|
| `imap.py` | Poll Gmail IMAP, parse RFC 822 messages, resolve original sender |
| `channels/telegram.py` | Receive Telegram webhook updates (user-forwarded SMS) |
| `sanitizer/` | Strip OTPs, account numbers, PII; extract structured `CleanPayload` |
| `hermes.py` | POST `CleanPayload` to `gateway_server.py` via HTTP |
| `config.py` | Load and validate configuration from environment variables |
| `__main__.py` | Poll loop — `imap.py` → `sanitizer` → `hermes.py` |

The forwarder holds no state, no database, no retry queue. If dispatch fails, the message is dropped — financial notifications are ephemeral by nature.

**Gateway payload schema (`CleanPayload`):**
```json
{
  "amount": 45000.0,
  "currency": "COP",
  "date": "2026-10-20T18:00:00Z",
  "transaction_type": "debit",
  "account_type": "checking",
  "channel": "email",
  "merchant": "RAPPI"
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
| `bank_learning` | Learn new bank notification formats from user-provided samples; fallback when sanitizer has no pattern match |

All skills are loaded by Hermes at runtime from the `skills/` directory.

### Bank Learning Skill (`skills/bank_learning/`)

The sanitizer uses a two-layer fallback to match incoming messages:

```
Message arrives at sanitizer
        │
        ▼
① Community patterns   ← compiled from tests/fixtures/ at deploy time
        │ no match
        ▼
② Hermes learned       ← patterns stored in SQLite, discovered at runtime
        │ no match
        ▼
  bank_learning skill  ← asks user, infers pattern, updates layer ②
```

The skill operates in two modes:

**Reactive** — triggered automatically when both layers fail:

```
Sanitizer: no pattern match → triggers bank_learning skill

Hermes → Telegram: "I got a notification I couldn't parse.
                    Which bank sent it?"
User: "Davivienda"

Hermes: uses NVIDIA model to infer structure from the raw message
        (this is the ONE place in the system where Hermes sees
        pre-sanitization content — see security exception below)

Hermes → Telegram: "I think this is a debit purchase of $85,000
                    at Éxito on 14/09/2026. Correct?"
User: "yes" / "no, it's a transfer"

Hermes: stores confirmed pattern in SQLite (layer ②)
        discards the raw message immediately
        applies pattern — transaction is processed normally
```

**Proactive** — user-initiated when adding a new bank before any notifications arrive:

```
User → Telegram: "hermes add-bank"

Hermes: "Which bank? Which country?"
User: "Davivienda, Colombia"

Hermes: "Send me 2–3 sample notifications from Davivienda.
         Redact sensitive info first:
         • Replace account numbers with XXXX
         • Replace names with NAME
         • Replace amounts with XX.XXX,XX
         • Replace OTPs with 000000"

User: [pastes redacted samples, one per message]

Hermes: uses NVIDIA model to infer fields: amount format,
        merchant position, date format, fields to strip

Hermes → Telegram: "I detected:
         • Amount: Colombian format ($XX.XXX,XX)
         • Merchant: extracted from 'Compraste X en MERCHANT'
         • Strips: account suffix, phone numbers
         Looks right?"

User: "yes" / corrections

Hermes: stores pattern in SQLite (layer ②)
        optionally generates fixture .txt + .expected.json files
        and saves them locally so the user can PR them to the
        community repo (tests/fixtures/) if they want
```

**Security exception — raw message access:**

In reactive mode only, Hermes briefly accesses the raw pre-sanitization message to
infer the pattern. This is the single documented exception to the privacy boundary rule.
Constraints that must be enforced:

- The raw content is passed to the NVIDIA model for structural inference only
- It is never stored, never logged, never written to SQLite
- The model call uses a system prompt that instructs it not to include values in its output — only structure (field positions, delimiters, formats)
- Once the pattern is stored, all subsequent messages from that bank are sanitized before Hermes sees them
- If the user declines to confirm the inferred transaction, the raw content is discarded and the transaction is dropped

### Config (`config/`)

```
config/
├── hermes.yaml          # Hermes runtime config — no secrets
├── openshell/
│   └── policy.yaml      # Sandbox policy — filesystem + network constraints
└── prompts/             # System prompts and skill prompt templates
```

## Data Flow: Happy Path (Email)

1. Bank sends email to the user's Gmail: `"Compra por $45,000 en RAPPI. Tarjeta terminada 1234."`
2. Forwarder IMAP poller fetches it (polls every 5 min, searches UNSEEN from bank sender)
3. Forwarder POSTs `{channel, from, subject, body}` to `gateway_server.py` on port 8080
4. `gateway_server.py` invokes `hermes send` to deliver the message to the user's Telegram chat
5. Hermes runs `expense_tracker` → stores in SQLite
6. Hermes runs `categorizer` → tags as `food`

## Data Flow: SMS (iPhone)

1. Bank sends SMS to the user's iPhone
2. iPhone Shortcut fires: sends the SMS body to **Saved Messages** (self-chat)
3. Pyrogram listener (`scripts/sms_listener.py`) detects the new message
4. Listener sends the text to the bot as a real user message, leaving the original intact
5. Forwarder Telegram adapter receives the message → sanitizer strips account suffix → emits `CleanPayload`
6. Hermes stores and categorizes the transaction

## Data Flow: Cash Operation

1. Bank SMS arrives via the iPhone flow above
2. Sanitizer emits clean payload with `transaction_type: cash`
3. Hermes stores the transaction, then sends Telegram reminder:
   `"Cash withdrawal of $100 detected. Add a description? (e.g., groceries, taxi)"`
4. User replies optionally; Hermes updates the record

## Data Flow: Debt Tracking

User tells Hermes directly via Telegram:
`"I paid dinner for João, he owes me $35"`

Hermes runs `debt_tracker` skill → stores entry in SQLite. No forwarder involved.

## Infrastructure

- **AWS EC2 t2.micro** hosts Hermes and the forwarder (free tier)
- **Elastic IP** keeps the instance address stable across restarts
- **NVIDIA open models** (via Nebius Serverless) handle all LLM inference
- **SQLite** is local to the Hermes agent's persistent storage volume on EC2
- The user's Telegram bot is the sole communication channel in both directions

## Privacy Properties

Because this is a single-user self-hosted deployment:

- The Telegram bot token belongs to the user — no third party can read their messages
- Gmail credentials (App Password) are stored only in the user's `.env` on their EC2 instance
- The SQLite database never leaves their EC2 volume
- The OpenShell policy prevents the agent from reaching outside its allowed endpoints
- Raw financial notifications are sanitized before Hermes ever sees them
- No email content transits third-party routing services — the forwarder polls Gmail directly
