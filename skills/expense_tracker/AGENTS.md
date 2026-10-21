# expense_tracker skill

Entry point of the transaction pipeline. Stores every clean transaction the forwarder
captures in SQLite, then hands it to `categorizer` (always) and `debt_tracker`
(transfers only). Also lets the user add descriptions to past transactions.

## Inputs

The clean payload from the forwarder, delivered by `gateway_server.py` as a
`NEW_TRANSACTION` message:
```json
{
  "amount": 32500.00,
  "currency": "COP",
  "merchant": "UBER RIDES",
  "date": "2026-09-16T01:35:00Z",
  "transaction_type": "debit",
  "account_type": "checking",
  "channel": "sms"
}
```

Only these seven fields are allowed. `merchant` is optional (transfers and cash have none).

## Normal flow

1. Validate the payload — reject unknown fields, non-positive amounts, non-UTC dates,
   unknown `transaction_type` / `channel`
2. Compute `message_hash` and check for a duplicate
3. Insert the transaction (category still NULL)
4. Run `categorizer` with the new transaction id
5. If `transaction_type` is `transfer_in` / `transfer_out`, run `debt_tracker` to look
   for a matching open debt
6. If `transaction_type` is `cash`, prepare the cash reminder question
7. Return either `NO_REPLY` or one message for the user (see Output contract)

## Duplicate detection

The same purchase often arrives twice — by email **and** by SMS. The hash therefore
excludes `channel`:

```
message_hash = SHA256(amount | date | transaction_type | merchant)
```

A duplicate is not an error: the skill stops silently and answers `NO_REPLY`.

## Accounts

The clean payload carries no account number (by design — see `docs/rules/security.md`),
but `transactions.account_id` is required. Transactions are grouped into one synthetic
account per `(account_type, currency)`, e.g. `auto-checking-cop`, created on demand.

## Output contract

Flow A runs unattended. The agent's final answer is relayed verbatim to Telegram by
`gateway_server.py`, so it must be exactly `NO_REPLY` or one short user-facing message
(cash reminder, gateway clarification, transfer-match question). Digital purchases that
categorize cleanly produce `NO_REPLY` — the user sees them in the daily summary
(`notifications.cash_operations_only` in `config/hermes.yaml`).

## Tools this skill uses

### `store_transaction`

Validates the payload (stdin) and inserts it:
```sql
SELECT id FROM transactions WHERE message_hash = ?;
INSERT OR IGNORE INTO accounts (id, bank, alias, type, currency, created_at) VALUES (...);
INSERT INTO transactions (id, account_id, amount, currency, merchant, date,
    transaction_type, channel, message_hash, created_at, updated_at) VALUES (...);
```

### `check_duplicate`

Same validation and hash, read-only.

### `update_transaction`

Sets the user-provided description or the recurring flag:
```sql
UPDATE transactions SET description = ?, updated_at = ? WHERE id = ?;
UPDATE transactions SET is_recurring = ?, updated_at = ? WHERE id = ?;
```

### `list_recent`

Latest transactions, so the user can refer to "the last one" without an id:
```sql
SELECT * FROM transactions [WHERE transaction_type = ?] ORDER BY date DESC LIMIT ?;
```

Every transaction is shown to the user with a 6-character short id (first 6 chars of
the UUID) that they can type back.

## What NOT to do

- Do not pass the payload on the command line — merchant names can contain quotes; use stdin
- Do not "repair" a rejected payload by dropping fields — an unexpected field means raw
  content may be leaking; drop the transaction
- Do not tell the user about duplicates
- Do not ask the user for account or card numbers
- Do not call `categorizer` before the transaction is stored
