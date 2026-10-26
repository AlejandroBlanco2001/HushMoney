# categorizer skill

Tags each incoming transaction with a spending category chosen from the user's own
category list. The gateway auto-categorizes via a merchant cache + LLM fallback.
This skill handles corrections and manual categorization from the Hermes agent.

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

## Cache-first flow

The `merchants` table is the primary cache. On each transaction:

1. Look up the normalized merchant name in `merchants`.
2. **Cache hit, `needs_clarification=0`**: use the stored `category` directly — no LLM call.
3. **Cache hit, `needs_clarification=1`**: merchant is a payment gateway or multi-service
   platform. Ask the user to confirm the category; use `last_category` to pre-fill the
   prompt ("Is this RAPPI charge food again?").
4. **Cache miss**: call the LLM (see below), then store the result in `merchants`.

The cache key is the normalized merchant string (`UPPER` + whitespace-collapsed) exactly
as emitted by the bank. "UBER RIDES" and "UBER EATS" are separate entries — each bank
emits a consistent string, so per-string caching is correct.

## LLM inference (cache miss only)

Call `categorize_merchant.py` with the transaction payload. The model returns:

```json
{"category": "food", "needs_clarification": false}
```
or, for payment gateways / ambiguous platforms:
```json
{"category": null, "needs_clarification": true, "reason": "payment_gateway"}
```

Store the result in `merchants` via `save_merchant.py` so future transactions hit
the cache. If `needs_clarification=false`, also write the category to the transaction.

## Clarification flow

When `needs_clarification=true`, the gateway appends to the Telegram notification:
> ❓ What was this RAPPI charge for? (last time: food)

When the user replies, Hermes should:
1. `save_category.py --id <tx_id> --category <slug>`
2. `save_merchant.py --name "RAPPI" --needs-clarification --last-category <slug>`
   (updates `last_category` for next time — does not clear `needs_clarification`)
3. Confirm to the user.

## Scripts

| Script | Purpose |
|--------|---------|
| `lookup_cached_category.py --merchant <name>` | Query `merchants` table; fallback to transaction history |
| `categorize_merchant.py --merchant <name> --payload <json>` | LLM inference (Nebius) |
| `save_merchant.py --name <name> [--category <slug>] [--needs-clarification] [--last-category <slug>]` | Upsert merchant cache entry |
| `save_category.py --id <tx_id> --category <slug>` | Write category to transaction |
| `get_categories.py` | Return category list (SQLite, falls back to hardcoded) |

## Schema

```sql
-- categories: canonical slug list, seeded with the defaults by config/schema.sql
CREATE TABLE categories (
    slug TEXT PRIMARY KEY, label TEXT NOT NULL, description TEXT, created_at TEXT NOT NULL
);

-- merchants: cache keyed by normalized bank-emitted name
CREATE TABLE merchants (
    name                TEXT PRIMARY KEY,
    category            TEXT REFERENCES categories(slug),  -- NULL if needs_clarification
    needs_clarification INTEGER NOT NULL DEFAULT 0,
    last_category       TEXT REFERENCES categories(slug),  -- last user-confirmed, for prompt pre-fill
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
```

## What NOT to do

- Do not skip `lookup_cached_category.py` — every transaction should check the cache first.
- Do not call the LLM for merchants where `needs_clarification=1` — ask the user instead.
- Do not clear `needs_clarification` after a user reply — ambiguous merchants stay ambiguous.
- Do not hardcode a category list — always read from SQLite via `get_categories.py`.
