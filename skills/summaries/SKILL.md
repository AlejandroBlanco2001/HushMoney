---
name: summaries
description: Generate daily, weekly, and monthly spending summaries
version: 0.3.0
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
- "la semana pasada" / "last week" / weekly cron → `--period week --offset -1`
- "este mes" / "this month" → `--period month`
- "el mes pasado" / "last month" / monthly cron → `--period month --offset -1`
- Custom range → `--from YYYY-MM-DD --to YYYY-MM-DD` (both days included)
- No qualifier (e.g. "how much did I spend?") → `--period month`

The crons run on Monday and on the 1st, so they must use `--offset -1`: the closed
week or month, not the few hours of the new one.

Run:
```
python3 /root/.hermes/skills/hushmoney/summaries/scripts/query_transactions.py \
  --period <period> [--offset -1]
```

Spending excludes money in (`transfer_in`, `credit`), which is reported separately in
`income_by_currency`. `transfer_out` **counts as spending** — money left the account.
Never add it to `--exclude-types`.

Week and month periods are compared with the previous period of the same length so
far (Monday–Wednesday vs. last Monday–Wednesday; a closed week vs. the full week
before). Each `spending_by_category` entry carries a `trend` with `delta_pct`,
`delta_amount` and `direction` (`up` | `down` | `flat` | `no_data`), and
`biggest_change` holds the category that moved the most per currency. `today` and
custom ranges have no comparison (`trend` and `previous` are null).

### Step 2 — Format the response

**Week and month (`text` is not null):** send `text` exactly as returned — it already has
the totals per category, the trend arrows and the biggest change. Do not rewrite it,
reorder it, or add your own percentages.

**Specific questions** ("¿gasté más en comida que la semana pasada?"): answer in one or
two sentences using only `trend` / `biggest_change` from the JSON. If `direction` is
`no_data`, say there is nothing to compare against.

**Today and custom ranges (`text` is null):** parse the JSON. If `count == 0`:
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
- **Weekly** (Monday 09:00): `--period week --offset -1`, always send `text`
- **Monthly** (1st 09:00): `--period month --offset -1`, always send `text`

## Pitfalls

- Never invent transactions — only report what `query_transactions.py` returns.
- Do not add different currencies into a single total.
- Never compute percentages or differences yourself — use `trend` and `biggest_change`.
- Daily summaries have no trends; do not compare today with yesterday.
- Do not exclude `transfer_out` from spending queries. A transfer out is outgoing money and counts as spending.
- If `query_transactions.py` errors (DB missing), reply:
  > "No transactions recorded yet. I'll start tracking once your first bank notification arrives."
