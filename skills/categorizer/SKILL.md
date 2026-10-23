---
name: categorizer
description: Tag each transaction with a spending category
version: 0.3.0
author: hushmoney
metadata:
  hermes:
    tags: [Categorization, Expenses]
    category: hushmoney
    requires_tools: [terminal]
---

# Categorizer

## When to Use

- Called after `expense_tracker` stores a manual transaction
- When user corrects a category: "that UBER was work, not transport"
- When user answers a clarification prompt for an ambiguous merchant

Automatic bank SMS/email transactions are auto-categorized by `gateway_server.py`
using the merchant cache — this skill handles AI-assisted and correction cases.

## Procedure

### Categorize a transaction

1. **Merchant cache lookup**:
   ```
   python3 /root/.hermes/skills/hushmoney/categorizer/scripts/lookup_cached_category.py \
     --merchant "<MERCHANT>"
   ```
   - `found=true, needs_clarification=false`: use `category`, skip to step 4.
   - `found=true, needs_clarification=true`: skip to step 3 (ask user).
   - `found=false`: continue to step 2.

2. **Infer from merchant name**:
   ```
   python3 /root/.hermes/skills/hushmoney/categorizer/scripts/get_categories.py
   ```
   Match the merchant (case-insensitive substring) against each category's keywords.
   If no clear match: use `other`. For obvious gateways/platforms (Rappi, PayU, Amazon)
   set `needs_clarification=true`.

3. **Save merchant to cache**:
   ```
   # Unambiguous merchant:
   python3 /root/.hermes/skills/hushmoney/categorizer/scripts/save_merchant.py \
     --name "<MERCHANT>" --category <slug>

   # Ambiguous merchant (payment gateway / multi-service platform):
   python3 /root/.hermes/skills/hushmoney/categorizer/scripts/save_merchant.py \
     --name "<MERCHANT>" --needs-clarification [--last-category <slug>]
   ```

4. **Save category to transaction**:
   ```
   python3 /root/.hermes/skills/hushmoney/categorizer/scripts/save_category.py \
     --id <transaction_id> --category <slug>
   ```

### Correct a category

When user says "that was X not Y":
1. Identify the transaction (most recent matching merchant; ask if ambiguous)
2. `save_category.py --id <id> --category <new_slug>`
3. Update the merchant cache if appropriate:
   - If the correction reveals a consistent new category: `save_merchant.py --name "<MERCHANT>" --category <new_slug>`
   - If the correction reveals the merchant is ambiguous: `save_merchant.py --name "<MERCHANT>" --needs-clarification --last-category <new_slug>`
4. Confirm: "✅ Updated — MERCHANT marked as [new category]."

### Handle a clarification reply

When user answers "that Rappi charge was food":
1. `save_category.py --id <tx_id> --category <slug>`
2. Update `last_category` in the merchant cache:
   ```
   python3 /root/.hermes/skills/hushmoney/categorizer/scripts/save_merchant.py \
     --name "RAPPI" --needs-clarification --last-category <slug>
   ```
3. Confirm: "✅ Got it — RAPPI marked as food."

## Category Slugs

`food` · `transport` · `entertainment` · `health` · `shopping` · `services` · `transfers` · `cash` · `other`

## Pitfalls

- Use only the slugs above — never invent new ones.
- UBER RIDES → transport, NETFLIX → entertainment. Don't ask for obvious ones.
- `transfer_in` / `transfer_out` → always `transfers`.
- Rappi, Amazon, PayU → always `needs_clarification`. Never guess for these.
- The merchant cache key is the exact normalized name from the bank (UPPER + collapsed whitespace).
  "UBER RIDES" and "UBER EATS" are separate entries — don't merge them.
