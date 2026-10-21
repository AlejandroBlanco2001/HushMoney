---
name: expense_tracker
description: Persist incoming transactions into SQLite
version: 0.1.0
author: hushmoney
metadata:
  hermes:
    tags: [Expenses, Transactions]
    category: hushmoney
    requires_tools: [terminal]
---

# Expense Tracker

## When to Use
Called automatically for every `CleanPayload` that arrives at the gateway. Do not ask the user for confirmation — just store it and report back.

## Procedure

1. **Compute the message hash** — SHA-256 of `{amount}:{date}:{transaction_type}:{account_type}` (colon-separated, amount as the raw float). You can skip this step and let `store_transaction.py` compute it, or pass `--message-hash` explicitly if you want to check for duplicates first.

2. **Check for duplicates** (optional but cheap):
   ```
   python3 skills/expense_tracker/scripts/check_duplicate.py --hash <hash>
   ```
   If `duplicate: true`, stop — the transaction was already recorded.

3. **Store the transaction**:
   ```
   python3 skills/expense_tracker/scripts/store_transaction.py \
     --amount <amount> \
     --currency <currency> \
     --date <ISO 8601 UTC date> \
     --transaction-type <debit|credit|cash|transfer_in|transfer_out|payment|top_up> \
     --account-type <checking|savings|credit|digital_wallet> \
     --channel <email|sms> \
     [--merchant <MERCHANT>] \
     [--bank <bank_slug>]
   ```
   The script is idempotent — a duplicate hash produces `{"ok": true, "duplicate": true}` without inserting.

4. **Pass the transaction ID** to the `categorizer` skill so the transaction gets tagged.

## Bank Slug
Use lowercase, no spaces: `bancolombia`, `davivienda`, `nequi`, `bbva`. If the bank is unknown, omit `--bank` and it defaults to `unknown`. The account will be created automatically on first use.

## Pitfalls
- Never write transaction data to files. Always use `store_transaction.py`.
- Do not store raw notification text anywhere — the payload arriving here is already sanitized.
- `--date` must be ISO 8601 UTC (e.g. `2026-10-21T09:56:00Z`). Convert local times before passing.

## Verification
After storing, confirm with the user only for cash operations (the gateway handles this — see `notifications.cash_operations_only` in `hermes.yaml`). For all other transaction types, store silently.
