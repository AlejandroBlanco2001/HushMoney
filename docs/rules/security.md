# Security Rules

These rules protect user financial data. They apply to every component but are most critical in `forwarder/` and `config/`. Read before touching either.

## The Privacy Boundary

The forwarder sanitizer is the **only** place in the system where raw financial notification content is handled. Everything downstream of it — Hermes, skills, SQLite, Telegram — works exclusively with clean payloads.

**This boundary must never be crossed in either direction:**
- Raw data must not bypass the sanitizer and reach Hermes
- Clean payloads must not be enriched with raw data after the fact

**There is exactly one documented exception:** the `bank_learning` skill in reactive mode
briefly accesses a raw message to infer its structure when the sanitizer has no matching
pattern. The constraints for this exception are strict — see the security exception rules
at the bottom of this file.

## What Must Be Stripped by the Sanitizer

The sanitizer must remove or redact all of the following before emitting a clean payload:

| Data type | Examples |
|---|---|
| OTPs and verification codes | `OTP: 882910`, `Your code is 554321` |
| Full or partial account numbers | `account ending 1234`, `card **9876` |
| Card numbers (full or partial) | `XXXX-XXXX-XXXX-1234` |
| Full recipient/sender names | `Transfer to John Smith` |
| IBAN / routing numbers | Any string matching IBAN or ABA routing format |
| URLs in bank messages | Often tracking links; strip entirely |
| Raw balance figures | Current balance is not a transaction event |
| **Bre-B llaves** | `la llave 1001820876`, `la llave @usuario`, `la llave 3001234567`, `la llave user@email.com` |

**Bre-B llaves** deserve special attention. Bre-B is Colombia's national instant payment
network — every major Colombian bank uses it. A "llave" is a user's universal payment
alias and can be a national ID (cédula), a phone number, an email, or an alphanumeric
handle. All four forms are equally sensitive and must be stripped. The pattern is
positional: strip from `la llave ` to the next date token (`el DD/MM`), without trying
to classify the type. See `tests/fixtures/BREB.md` for the full reference.

The clean payload may only contain: `amount`, `currency`, `merchant` (normalized), `date`, `transaction_type`, `account_type`, `channel`.

## Logging Rules

- **Never log the raw message payload** from any input channel (email body, SMS text, Telegram message)
- **Never log any field from the pre-sanitization data** — even partial account numbers or merchant names that appear before sanitization completes
- Logging is allowed for: sanitization outcome (`"sanitized ok"`, `"pattern not matched"`), dispatch status (`"dispatched to hermes"`), and errors with no payload content
- Log IDs, not values: log `transaction_id=abc123`, never `amount=42.50 merchant=Starbucks`

## Secrets and Credentials

- Secrets (API keys, bot tokens, database passwords) go in environment variables only — never in `config/hermes.yaml` or any committed file
- Use a `.env.example` file with placeholder values to document which secrets are needed
- Never commit a `.env` file — it must be in `.gitignore`
- Rotate any secret that was accidentally committed, even briefly

## Input Validation

- Treat every incoming message from every channel as untrusted input
- Validate and normalize the clean payload schema before dispatching to Hermes — reject malformed payloads at the forwarder boundary
- Do not trust merchant names or descriptions from input messages to be safe strings — sanitize for injection before storing

## Telegram

- The Telegram bot token must never appear in logs or error messages
- Only send messages to the pre-configured user chat ID — never dynamically resolve recipients from message content
- Telegram messages sent to the user must not include any raw financial data; use only normalized fields from the clean payload

## OpenShell Policy

- The OpenShell sandbox policy (`config/openshell/policy.yaml`) must restrict the agent to:
  - Read/write access to the SQLite database path only
  - Network access to Nebius inference endpoints only
  - No access to the host filesystem outside the sandbox
- Any change to `config/openshell/policy.yaml` requires explicit team review — it is a security control, not a config file

## bank_learning Exception Rules

The `bank_learning` skill is the **only** component allowed to access raw pre-sanitization
content, and only under these conditions:

- **Reactive mode only** — raw access is never permitted in proactive mode (user provides
  already-redacted samples)
- The raw message is passed to the NVIDIA model with a system prompt that instructs it to
  return **only structural information** (field positions, delimiters, date formats) —
  never to echo, summarize, or reproduce values from the message
- The raw message is held in memory only for the duration of the model call — it is never
  written to SQLite, never logged, never sent over the network except to the inference endpoint
- The inferred transaction values (amount, merchant, date) are shown to the user for
  confirmation before being stored — if the user does not confirm, the transaction is dropped
  and the raw content is discarded
- If you are modifying `skills/bank_learning/`, this checklist applies in addition to the
  standard one below

## Code Review Checklist for Security-Sensitive PRs

Before merging any change to `forwarder/`, `config/`, or `skills/bank_learning/`:

- [ ] No raw payload fields appear in any log statement
- [ ] No secret values are hardcoded or committed
- [ ] The sanitizer strips all data types listed above
- [ ] The clean payload schema is validated before dispatch
- [ ] OpenShell policy is unchanged (or change is explicitly justified)
- [ ] If touching `bank_learning`: raw message is not stored or logged; model prompt
      instructs structural-only output; user confirmation is required before any write
