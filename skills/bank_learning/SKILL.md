---
name: bank_learning
description: Learn new bank notification formats at runtime
version: 0.2.0
author: hushmoney
metadata:
  hermes:
    tags: [BankLearning, Parsing]
    category: hushmoney
    requires_tools: [terminal]
---

# Bank Learning

## When to Use

Triggered manually when the user shares a bank SMS the system didn't recognize
(pastes raw text and says "teach it this" or "add this bank").

Note: the forwarder drops unmatched SMS without forwarding them. The user must
paste the raw text manually for learning.

## Procedure

### Step 1 — Identify the bank

Ask (or infer from the text): which bank sent this SMS?

### Step 2 — Extract and confirm the pattern

Analyze the raw SMS text to extract:
- `transaction_type`: debit / credit / transfer_out / transfer_in / payment / cash
- `account_type`: checking / savings / credit / digital_wallet
- Amount, merchant, date (with the regex patterns that match them)

Show extracted values for confirmation:
> I parsed: Amount 45,000 · Merchant RAPPI · Date 21/10/2026 14:32
> Does this look right?

### Step 3 — Store if confirmed

```
python3 /root/.hermes/skills/hushmoney/bank_learning/scripts/store_pattern.py \
  --bank <slug> \
  --country CO \
  --channel sms \
  --pattern '<json>' \
  --confirmed
```

Pattern JSON format:
```json
{
  "transaction_type": "debit",
  "account_type": "checking",
  "amount_regex": "\\$([\\d.,]+)",
  "merchant_regex": "en (.+?) con",
  "date_regex": "(\\d{2}/\\d{2}/\\d{4})"
}
```

Tell the user:
> ✅ Pattern saved for [Bank]. Note: the forwarder also needs a `BankPatterns` entry
> in `banks.py` before it can route these SMS automatically.

### Step 4 — Check existing patterns (optional)

```
python3 /root/.hermes/skills/hushmoney/bank_learning/scripts/query_patterns.py \
  --bank <slug> --channel sms
```

## Pitfalls

- Always confirm with the user before storing.
- A DB pattern alone is not enough for auto-forwarding — the forwarder `banks.py` also needs updating.
