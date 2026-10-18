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
| `confirm.py` | `/confirm` endpoint — receives Gmail confirmation code intercepted by Cloudflare and relays it to Hermes during automated setup |

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
| `bank_learning` | Learn new bank notification formats from user-provided samples; fallback when sanitizer has no pattern match |

All skills run inside the NVIDIA OpenShell sandbox. Policy at `config/openshell/policy.yaml`.

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

**Contributing a learned pattern back:**

If the user confirms a pattern is working correctly after a week of real transactions,
Hermes can generate the fixture files and prompt:

```
Hermes → Telegram: "Davivienda patterns have been working for 7 days with
                    no corrections. Want me to generate fixtures for the
                    community repo so others benefit too?"
User: "yes"
Hermes: writes tests/fixtures/emails/davivienda/ and sms/davivienda/
        with synthetic samples matching the learned pattern
```

User opens a PR — the pattern enters the community layer.

**Security exception — raw message access:**

In reactive mode only, Hermes briefly accesses the raw pre-sanitization message to
infer the pattern. This is the single documented exception to the privacy boundary rule.
Constraints that must be enforced:

- The raw content is passed to the NVIDIA model for structural inference only
- It is never stored, never logged, never written to SQLite
- The model call uses a system prompt that instructs it not to include values in its output — only structure (field positions, delimiters, formats)
- Once the pattern is stored, all subsequent messages from that bank are sanitized before Hermes sees them
- If the user declines to confirm the inferred transaction, the raw content is discarded and the transaction is dropped

### Setup Skill (`skills/setup/`)

Hermes orchestrates the entire setup without the user having to click anything in a browser. It uses the **Playwright MCP server** to drive the user's already-logged-in Chrome, with **Human-in-the-Loop (HITL) checkpoints** via Telegram before any significant action.

The Cloudflare Email Worker intercepts Gmail's confirmation email during setup and relays the code to the forwarder's `/confirm` endpoint, which passes it back to Hermes — so even the email confirmation step is handled automatically.

```
User → Telegram: "hermes setup"

── Phase 1: Telegram bot ───────────────────────────────────────────
Hermes → Telegram: "Open @BotFather, send /newbot, paste the token here."
User → Telegram: [pastes token]
Hermes: stores token, validates it works

── Phase 2: Gmail forwarding (automated via Playwright MCP) ────────
Hermes → Playwright MCP: open Chrome (user's existing profile, already logged in)
Hermes → Playwright MCP: navigate to Gmail Settings → Forwarding
Hermes → Telegram (HITL checkpoint):
  "I'm about to add a forwarding address to your Gmail.
   [screenshot attached]
   Confirm to proceed, or cancel."
User → Telegram: "confirm"
Hermes → Playwright MCP: add hushmoney address, submit

  [Gmail sends a confirmation email to the HushMoney address]
  [Cloudflare Email Worker intercepts it, POSTs to forwarder /confirm]
  [Forwarder extracts the 9-digit code, calls Hermes]

Hermes → Playwright MCP: enter confirmation code, click verify
Hermes → Telegram (HITL checkpoint):
  "Forwarding confirmed. Now add a filter so only your bank's
   emails forward (not everything). Which bank?"
User → Telegram: "Santander"
Hermes → Playwright MCP: create Gmail filter for sender address, save
Hermes → Telegram: "Filter set. Send a test transaction and I'll confirm receipt."

── Phase 3: SMS redirect (Android) ─────────────────────────────────
Hermes → Telegram: "For SMS alerts: do you use Android or iOS?"
User → Telegram: "Android"
Hermes → Playwright MCP: open Tasker profile download page (or generate profile XML)
Hermes → Telegram:
  "Download this Tasker profile and import it. It will auto-forward
   bank SMS to this bot. [file attached / link]
   Reply 'done' once imported."
User → Telegram: "done"
Hermes → Telegram: "Send yourself a test SMS or wait for the next bank alert."

── Phase 4: Verification ────────────────────────────────────────────
Hermes waits up to 10 minutes for a test payload to arrive via either channel.
Hermes → Telegram: "All set. HushMoney is running."
```

**HITL checkpoints** — Hermes asks for confirmation before:
- Adding the Gmail forwarding address
- Creating the Gmail filter
- Any step that writes to external services

After setup completes, the `setup` skill marks itself done and will not re-run unless explicitly reset with `hermes setup --reset`.

**SMS redirect — Android vs. iOS:**

| Platform | Approach |
|---|---|
| Android | Hermes generates a Tasker profile XML pre-configured with the bot token and bank sender numbers. User imports it — one tap. Auto-forwards matching SMS to the Telegram bot with no further action. |
| iOS | Apple's sandbox prevents background SMS interception. Best path: switch bank notification channel from SMS to email in the banking app settings. Hermes guides this via Playwright (bank's web portal) using the same HITL pattern. Alternatively, iOS Shortcuts can be triggered by banking app push notifications and POST to the forwarder webhook — Hermes provides the Shortcut as a downloadable `.shortcut` file. |

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
