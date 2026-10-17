# Security Rules

These rules protect user financial data. They apply to every component but are most critical in `forwarder/` and `config/`. Read before touching either.

## The Privacy Boundary

The forwarder sanitizer is the **only** place in the system where raw financial notification content is handled. Everything downstream of it — Hermes, skills, SQLite, Telegram — works exclusively with clean payloads.

**This boundary must never be crossed in either direction:**
- Raw data must not bypass the sanitizer and reach Hermes
- Clean payloads must not be enriched with raw data after the fact

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

## Code Review Checklist for Security-Sensitive PRs

Before merging any change to `forwarder/` or `config/`:

- [ ] No raw payload fields appear in any log statement
- [ ] No secret values are hardcoded or committed
- [ ] The sanitizer strips all data types listed above
- [ ] The clean payload schema is validated before dispatch
- [ ] OpenShell policy is unchanged (or change is explicitly justified)
