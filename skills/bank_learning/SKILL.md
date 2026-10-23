---
name: bank_learning
description: Learn new bank notification formats at runtime
version: 0.3.0
author: hushmoney
metadata:
  hermes:
    tags: [BankLearning, Parsing]
    category: hushmoney
    requires_tools: [terminal]
---

# Bank Learning

## When to Use

Triggered automatically when the forwarder receives a financial notification it cannot
parse. The message arrives with a `[bank_learning]` header — **only the redacted text
is present, never the original values**.

Also triggered manually if the user says "teach it this bank" and pastes a redacted
sample.

## Security rules (read before every run)

- The text you receive is already redacted: amounts show as `[REDACTED]`, account
  numbers as `[REDACTED]`, etc.
- Never ask the user to paste raw (unredacted) content.
- Never reproduce the redacted text verbatim in your reply — work from structure only.
- The `fingerprint` in the header is your deduplication key; always include it in
  proposals.

## Message format

An auto-triggered message looks like:

```
[bank_learning]
reason: no_template
channel: sms
bank: unknown
fingerprint: a1b2c3d4e5f6a7b8
---
Bancolombia: Su cuenta *1234 fue debitada por $[REDACTED]. Compra en [REDACTED].
```

`reason` values:
- `bank_unknown` — sender not recognized at all
- `no_template` — bank recognized but no matching pattern
- `date_failed` — pattern matched but date extraction failed
- `invalid_amount` — pattern matched but amount could not be parsed
- `pending_repeat` — same unknown pattern seen again while a previous learning request is still open; **skip pattern teaching, go straight to Step 3** (ask for amount + date to record this specific transaction manually via expense_tracker)

## Procedure

### Step 1 — Get registry context

```
python3 /root/.hermes/skills/hushmoney/bank_learning/scripts/get_bank_context.py \
  [--bank SLUG]
```

This shows known banks, their existing templates, and separators. Use it to understand
the current state before proposing anything.

### Step 2 — Infer the pattern from structure

Analyze the **structure** of the redacted text (word order, delimiters, label words).
Do NOT try to recover the original values.

Extract:
- `transaction_type`: debit / credit / transfer_out / transfer_in / payment / cash / top_up
- `account_type`: checking / savings / credit / digital_wallet
- A named-group regex:
  - Must have `(?P<amount>...)` capturing the amount (with separators, no currency symbol)
  - May have `(?P<merchant>...)` if a merchant name is present
  - Must be anchored to literal text (not generic wildcards)

### Step 3 — Ask the user to confirm expected values

Present what you inferred, then ask:

> From the structure I can see this looks like a **debit** on a **checking** account.
> To validate the pattern I need the original values:
> - Amount (number only, e.g. `45000.50`)
> - Transaction date (ISO format, e.g. `2026-10-21T14:32:00Z`)
> - Merchant name, if visible (optional)

Wait for the user's reply. Do not guess or fabricate these values.

### Step 4 — Submit the proposal

```
python3 /root/.hermes/skills/hushmoney/bank_learning/scripts/propose_pattern.py \
  --bank <slug> \
  --channel sms \
  --template-key <slug>_<type>_<account> \
  --regex '<regex>' \
  --sample '<redacted_text>' \
  --fingerprint <fingerprint_from_header> \
  --expected '{"amount": 45000.50, "transaction_type": "debit",
               "account_type": "checking",
               "date": "2026-10-21T14:32:00Z"}' \
  [--date-regex '<date_named_group_regex>'] \
  [--bank-profile '<json_for_unknown_bank>']
```

The forwarder validates and responds within ~2 seconds. Check the result file:

```
cat ~/.hermes/pattern-inbox/results/<proposal_id>.json
```

- `outcome: accepted` → pattern is now active as a candidate; tell the user.
- `outcome: rejected` → report the `rejections` to the user and ask for corrections.

### Step 5 — Handle rejection feedback

Common rejection codes and what to do:

| Code | Action |
|------|--------|
| `too_generic` | Add more literal text anchors to the regex |
| `missing_amount_group` | Add `(?P<amount>...)` to the regex |
| `no_match_on_sample` | The regex doesn't match the sample — fix it |
| `amount_mismatch` | The captured amount doesn't match `expected.amount` |
| `date_failed` | Provide a `--date-regex` override |
| `collides_with_existing` | Choose a more specific pattern or rename template-key |
| `rate_limited` | Too many proposals today; try tomorrow |

### Step 6 — Mark as ignored (optional)

If the user says they don't want to learn this notification type:

```
python3 /root/.hermes/skills/hushmoney/bank_learning/scripts/mark_ignored.py \
  --fingerprint <fingerprint>
```

### Step 7 — Report feedback on an active pattern (optional)

When the user says a parsed transaction was wrong:

```
python3 /root/.hermes/skills/hushmoney/bank_learning/scripts/report_feedback.py \
  --pattern-id <id> \
  --verdict wrong
```

Or confirms it was correct (helps promote candidate to active):

```
python3 /root/.hermes/skills/hushmoney/bank_learning/scripts/report_feedback.py \
  --pattern-id <id> \
  --verdict correct
```

## Candidate promotion

A pattern starts as `candidate` (marked 🧪 in transaction summaries). It auto-promotes
to `active` after 3 distinct successful uses with no corrections over 24 hours.

## Pitfalls

- Always confirm expected values with the user before submitting — never fabricate them.
- The sample must be the already-redacted text from the `[bank_learning]` message body.
- For unknown banks, supply `--bank-profile` with separators, timezone, date format.
- Do not attempt to decode `[REDACTED]` placeholders back to real values.
