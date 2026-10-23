---
name: summaries
description: Generate daily, weekly, and monthly spending summaries
version: 0.2.0
author: hushmoney
metadata:
  hermes:
    tags: [Summaries, Reporting]
    category: hushmoney
    requires_tools: [terminal]
    blueprint:
      - cron: "0 20 * * *"   # daily at 20:00
        trigger: daily_summary
      - cron: "0 9 * * 1"    # weekly on Monday at 09:00
        trigger: weekly_summary
      - cron: "0 9 1 * *"    # monthly on the 1st at 09:00
        trigger: monthly_summary
---

# Summaries

## When to Use

- Proactive: triggered by cron (daily/weekly/monthly)
- Reactive: triggered when user asks about spending ("how much did I spend?",
  "¿cuánto gasté?", "show my summary", "resumen de gastos", etc.)

## Procedure

### Step 1 — Determine period

Resolve the period from the user's message or the cron trigger:
- "hoy" / "today" / daily cron → `--period today`
- "esta semana" / "this week" → `--period week`
- "este mes" / "this month" / monthly cron → `--period month`
- Custom range → `--from YYYY-MM-DD --to YYYY-MM-DD`
- No qualifier (e.g. "how much did I spend?") → `--period month`

Run:
```
python3 /root/.hermes/skills/hushmoney/summaries/scripts/query_transactions.py \
  --period <period>
```

`transfer_in` is excluded by default (money arriving is not spending).
`transfer_out` **counts as spending** — money left the account. Never add it to `--exclude-types`.

### Step 2 — Format the response

Parse the JSON. If `count == 0`:
> No spending recorded for [period].

Otherwise, format an expressive summary. **Always include account and card info.**

#### Format example

```
📊 *Gastos de esta semana*

💳 Bancolombia débito (****1234)
  • UBER — COP 6,930 (Transporte)
  • RAPPI — COP 32,000 (Comida)
  Subtotal: COP 38,930

💳 Visa Bancolombia (****9012)
  • NETFLIX — COP 18,900 (Entretenimiento)
  Subtotal: COP 18,900

─────────────
Total: COP 57,830
```

Rules:
- Group by account alias (fallback: bank + type if no alias)
- Show card `masked_number` when `card` is not null
- Show category in parentheses when set; omit when null
- If multiple currencies, show a total per currency — never mix them
- List newest-first within each group; cap at 10 per account + "N more…"

#### Proactive cron rules

- **Daily** (20:00): skip if `count == 0` — no message when there's nothing to report
- **Weekly** (Monday 09:00): always send
- **Monthly** (1st 09:00): always send

## Pitfalls

- Never invent transactions — only report what `query_transactions.py` returns.
- Do not add different currencies into a single total.
- Do not exclude `transfer_out` from spending queries. A transfer out is outgoing money and counts as spending.
- If `query_transactions.py` errors (DB missing), reply:
  > "No transactions recorded yet. I'll start tracking once your first bank notification arrives."
