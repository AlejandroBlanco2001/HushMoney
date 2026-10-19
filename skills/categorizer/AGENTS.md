# categorizer skill

Tags each incoming transaction with a spending category chosen from the user's own
category list. Called by Hermes immediately after `expense_tracker` stores the record.

## Inputs

The clean payload from the forwarder:
```json
{
  "amount": 42.50,
  "currency": "USD",
  "merchant": "Starbucks",
  "transaction_type": "debit",
  "account_type": "checking",
  "channel": "email"
}
```

## Normal flow

1. Call the `get_categories` tool to fetch the user's current category list from SQLite
2. Build the categorization prompt with those categories injected dynamically
3. Call the NVIDIA model — expect `{"category": "<name>"}` back
4. Write the category to the transaction record in SQLite

## Payment gateway flow

Some merchants are payment processors (PayU, Stripe, Adyen, Pexto Capital, etc.) whose
name reveals nothing about the actual purchase. When the model returns:
```json
{"category": "needs_clarification", "reason": "payment_gateway"}
```

Hermes should:
1. Ask the user via Telegram: *"Payment of $X to MERCHANT — what was this for?"*
2. Categorize based on the user's reply
3. Store the `merchant → category` mapping in SQLite (`merchant_hints` table, see schema)

Prefer asking over guessing for these cases, even if a mapping already exists —
the same gateway may be used for different purposes. The stored hint is only used
to pre-fill the suggestion, not to skip the question entirely.

## Tools this skill uses

### `get_categories`

Reads the user's category list from SQLite. Hermes must call this before building
the prompt — never use a hardcoded list.

```sql
SELECT name FROM categories ORDER BY name;
```

The default set is seeded into SQLite on first run from `config/hermes.yaml`.
Users can add or remove categories via Telegram: *"hermes add category gambling"*.

### `set_transaction_category`

Writes the resolved category back to the transaction record:
```sql
UPDATE transactions SET category = ? WHERE id = ?;
```

### `store_merchant_hint`

Persists a merchant → category mapping so it can pre-fill the clarification prompt
next time the same gateway appears:
```sql
INSERT OR REPLACE INTO merchant_hints (merchant, category) VALUES (?, ?);
```

## What NOT to do

- Do not hardcode a category list in the prompt — always read from SQLite via `get_categories`
- Do not skip the clarification question for known payment gateways just because a hint exists
- Do not call this skill before `expense_tracker` has stored the transaction
