---
name: expense_tracker
description: Persist incoming transactions into SQLite
version: 0.2.0
author: hushmoney
metadata:
  hermes:
    tags: [Expenses, Transactions]
    category: hushmoney
    requires_tools: [terminal]
---

# Expense Tracker

## When to Use

Invoked when the user manually reports a transaction that didn't come through
a bank notification:
- Cash transactions: "I paid COP 5,000 cash for a coffee"
- Corrections: "I spent COP 45,000 at the pharmacy yesterday"

Automatic bank SMS/email transactions are stored directly by `gateway_server.py`
without going through this skill. Do not invoke this skill for those.

## Procedure

### Step 1 — Extract fields

- `amount`: numeric (required)
- `currency`: COP if not specified
- `date`: ISO 8601 UTC — use now if not mentioned
- `transaction_type`: debit / credit / cash / transfer_out / transfer_in / payment / top_up
- `account_type`: checking / savings / credit / digital_wallet — ask if unclear
- `channel`: always `telegram` for manually-reported transactions
- `merchant`: business name (optional)
- `bank`: bancolombia / davivienda / nequi / bbva / unknown

### Step 2 — Store

```
python3 /root/.hermes/skills/hushmoney/expense_tracker/scripts/store_transaction.py \
  --amount <amount> \
  --currency <currency> \
  --date <ISO 8601 UTC> \
  --transaction-type <type> \
  --account-type <account_type> \
  --channel telegram \
  [--merchant <MERCHANT>] \
  [--bank <slug>]
```

If `duplicate: true` in the response:
> That transaction looks like a duplicate — I already have it recorded.

### Step 3 — Categorize

```
python3 /root/.hermes/skills/hushmoney/categorizer/scripts/lookup_cached_category.py \
  --merchant "<merchant>"
```
If category found, save it:
```
python3 /root/.hermes/skills/hushmoney/categorizer/scripts/save_category.py \
  --id <id> --category <slug>
```

### Step 4 — Confirm

> ✅ Recorded: COP 5,000 · Coffee · [account alias or bank] · [category]

## Pitfalls

- `--date` must be ISO 8601 UTC (e.g. `2026-10-21T09:56:00Z`). Convert local times.
- `--channel` is always `telegram` for manually-reported transactions.
- Never write transaction data to files. Always use `store_transaction.py`.
