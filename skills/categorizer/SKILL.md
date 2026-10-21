---
name: categorizer
description: Tag each transaction with a spending category
version: 0.2.0
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
- When user asks to recategorize a transaction

Automatic bank SMS transactions are auto-categorized by `gateway_server.py`
using the cache lookup — this skill handles the AI-assisted and correction cases.

## Procedure

### Categorize a transaction

1. **Cache lookup**:
   ```
   python3 /root/.hermes/skills/hushmoney/categorizer/scripts/lookup_cached_category.py \
     --merchant "<MERCHANT>"
   ```
   If `category` is not null: skip to step 3.

2. **Infer from merchant name**:
   ```
   python3 /root/.hermes/skills/hushmoney/categorizer/scripts/get_categories.py
   ```
   Match the merchant (case-insensitive substring) against each category's `keywords`.
   If no match: use `other`. Never ask the user unless the transaction is ambiguous.

3. **Save**:
   ```
   python3 /root/.hermes/skills/hushmoney/categorizer/scripts/save_category.py \
     --id <transaction_id> --category <slug>
   ```

### Correct a category

When user says "that was X not Y":
1. Identify the transaction (most recent matching merchant; ask if ambiguous)
2. `save_category.py --id <id> --category <new_slug>`
3. Confirm: "✅ Updated — UBER marked as [new category]."

## Category Slugs

`food` · `transport` · `entertainment` · `health` · `shopping` · `services` · `transfers` · `cash` · `other`

## Pitfalls

- Use only the slugs above — never invent new ones.
- UBER → transport, RAPPI → food, NETFLIX → entertainment. Don't ask for obvious ones.
- `transfer_in` / `transfer_out` → always `transfers`.
