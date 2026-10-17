# Architecture

## System Overview

HushMoney has three layers: a **forwarder** that sanitizes raw financial notifications, **Hermes Agent** that processes clean signals and manages memory, and a **notification channel** (Telegram) for user-facing cash operation reminders.

```
┌──────────────────────────────────────────────────────────┐
│                     Input Sources                        │
│   Bank Email    Bank SMS    Messaging Apps               │
└────────┬────────────┬──────────────┬─────────────────────┘
         │            │              │
         └────────────┴──────────────┘
                      │
                      ▼
┌──────────────────────────────────────────────────────────┐
│                     Forwarder                            │
│   channels/      sanitizer/       dispatcher/           │
│   (adapters)  →  (strip PII)  →   (clean payload)       │
└──────────────────────────────┬───────────────────────────┘
                               │
                  { amount, merchant, date,
                    transaction_type, channel }
                               │
                               ▼
┌──────────────────────────────────────────────────────────┐
│                   Hermes Agent                           │
│                                                          │
│   ┌──────────────────────────────────────────────────┐  │
│   │                   skills/                        │  │
│   │  expense_tracker  categorizer  debt_tracker      │  │
│   │  summaries                                       │  │
│   └──────────────────────────────────────────────────┘  │
│                          │                               │
│                     ┌────┴────┐                          │
│                     │ SQLite  │                          │
│                     └─────────┘                          │
│                                                          │
│   Runtime: NVIDIA OpenShell sandbox                      │
│   Models:  NVIDIA open models via Nebius                 │
└──────────────────────────────┬───────────────────────────┘
                               │
                               ▼ (cash operations only)
                      Telegram Bot API
                      → User reminder
```

## Component Responsibilities

### Forwarder (`forwarder/`)

- Receives raw financial notifications from configured input channels
- Sanitizes every message before it leaves: removes OTPs, full account numbers, card numbers, recipient full names, and any other PII
- Emits a **clean payload** — a minimal structured object containing only what Hermes needs to act
- Stateless: no storage, no retry queues, no business logic

**Clean payload schema (draft):**
```json
{
  "amount": 42.50,
  "currency": "USD",
  "merchant": "Starbucks",
  "date": "2026-10-17T09:15:00Z",
  "transaction_type": "debit",
  "account_type": "checking",
  "channel": "sms"
}
```

### Hermes Agent + Skills (`skills/`)

Hermes is the AI reasoning layer. It receives clean payloads and orchestrates:

| Skill | Responsibility |
|---|---|
| `expense_tracker` | Persist the transaction into SQLite; attach description |
| `categorizer` | Classify transaction into a spending category |
| `debt_tracker` | Manage a list of people owed / owing |
| `summaries` | Generate daily, weekly, monthly rollups on schedule or on demand |

Skills run inside an **NVIDIA OpenShell** sandbox, which enforces policy-governed filesystem and network access. The OpenShell policy lives at `config/openshell/policy.yaml`.

### Config (`config/`)

- `hermes.yaml` — Hermes runtime configuration (model selection, skill paths, gateway settings). Non-secret behavior lives here, not in environment variables.
- `openshell/policy.yaml` — OpenShell sandbox policy (allowed filesystem paths, network endpoints, privilege constraints)
- `prompts/` — System prompts and skill prompt templates

### Notifications

Hermes sends a Telegram message only when a cash transaction is detected (i.e., the forwarder cannot automatically infer the merchant from a digital record). The user is asked to optionally add a description or confirm the category.

## Data Flow: Happy Path

1. Bank sends SMS: `"Your account ending 1234 was debited USD 42.50 at STARBUCKS on 17-Oct. OTP: 882910"`
2. Forwarder `channels/sms` adapter receives it
3. Forwarder `sanitizer` strips account suffix, OTP, and raw formatting → emits clean payload
4. Forwarder `dispatcher` POSTs clean payload to Hermes gateway
5. Hermes runs `expense_tracker` skill → stores transaction in SQLite
6. Hermes runs `categorizer` skill → tags as `dining`
7. Hermes stores description inferred from merchant name
8. No Telegram message sent (digital transaction, fully resolved)

## Data Flow: Cash Operation

1. Forwarder detects a cash withdrawal notification
2. Clean payload emitted with `transaction_type: cash`
3. Hermes stores the transaction with category `cash`
4. Hermes triggers Telegram reminder: `"Cash withdrawal of $100 detected. Add a description? (e.g., groceries, taxi)"`
5. User optionally replies; Hermes updates the record

## Infrastructure

- **Nebius AI Cloud** hosts the Hermes agent and OpenShell sandbox
- **NVIDIA open models** are used for all LLM inference (no OpenAI/Anthropic dependency)
- SQLite database is local to the Hermes agent's persistent storage volume
