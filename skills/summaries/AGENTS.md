# summaries skill

Generates daily, weekly and monthly spending summaries on schedule, and answers
on-demand questions ("¿cuánto gasté esta semana?", "¿cuánto en transporte en septiembre?").

All arithmetic happens in the script. The model never adds up amounts — a wrong total is
the one mistake users notice immediately.

## Inputs

- A scheduled trigger: `daily_summary`, `weekly_summary`, `monthly_summary`
- Or a user question on Telegram

## Schedule

| Trigger | When | Period covered |
|---|---|---|
| `daily_summary` | every day 20:00 | today |
| `weekly_summary` | Monday 09:00 | the Monday–Sunday week that just ended |
| `monthly_summary` | 1st of the month 09:00 | the month that just ended |

The `blueprint` block in `SKILL.md` documents this schedule. The jobs themselves are
registered once with `hermes cron create` (`--skill summaries`, delivery to the user's
Telegram chat).

## Normal flow

1. Map the trigger or question to a period: `--period today|week|month` with
   `--offset` (0 = current, -1 = previous), or an explicit `--from` / `--to`.
   Weekly and monthly crons use `--offset -1`: they run at the start of the new period
   and report the one that just closed.
2. Run `query_transactions` — it computes the totals and, for week and month, renders
   the message
3. Week or month → send the rendered `text` as is
4. Today or custom range → format the transactions from the JSON (`text` is null)
5. Specific question → answer in one or two sentences using only numbers from the JSON

## What counts as what

| Bucket | `transaction_type` |
|---|---|
| Spending | everything except income: `debit`, `payment`, `cash`, `transfer_out`, `top_up` |
| Income ("Recibido") | `transfer_in`, `credit` |

A credit-card purchase arrives as `debit` (on a `credit` account); `credit` as a
transaction type is money coming in, such as a refund.

## Time zone

Periods are the user's **local** days (`user_settings.timezone`, default
`America/Bogota`, UTC-5). Transactions are stored in UTC, so a purchase at
Sunday 22:30 Bogotá (`Monday 03:30Z`) belongs to Sunday.

## Comparison with the previous period

Only week and month periods are compared; `today` and custom ranges are not
(yesterday is not a useful baseline).

- A closed period is compared with the full previous one (last week vs. the week
  before; February vs. all of January).
- An open period is compared with the previous period **of the same length so far** —
  Monday–Wednesday vs. last Monday–Wednesday; March 1–30 vs. February 1–28 — so
  mid-period comparisons are fair.
- The comparison is per category **and currency**; currencies are never mixed.
- `delta_pct` is `null` and `direction` is `no_data` when the category had no spending
  in the previous period. Changes under 0.5% are `flat` ("→ igual").
- `biggest_change` is, per currency, the category with the largest change in money
  (categories without previous data are not candidates). Categories that dropped to
  zero still count, and appear in `spending_by_category` with `total: 0`.

## Tools this skill uses

### `query_transactions`
```sql
SELECT ... FROM transactions t JOIN accounts a ... LEFT JOIN cards c ...
WHERE t.date >= ? AND t.date < ? AND t.transaction_type NOT IN ('transfer_in', 'credit');
-- same query for the previous period, plus income:
SELECT currency, SUM(amount) FROM transactions
WHERE date >= ? AND date < ? AND transaction_type IN ('transfer_in', 'credit') GROUP BY currency;
```

Returns the transactions with account and card context, `total_by_currency`,
`spending_by_category` (with `trend`), `income_by_currency`, `previous`,
`biggest_change`, and `text` — the message rendered from `templates/weekly.md` or
`monthly.md`, with category labels and emoji from `assets/category_labels.json`
(categories the user added fall back to their label in `categories` and 🏷️).

Planned, not yet returned: top merchants, largest purchase, pending clarifications,
recurring merchants, active debt totals, and a rendered daily message.

## What NOT to do

- Do not compute or re-add totals in the model
- Do not rewrite or "improve" the rendered `text` — it keeps numbers exact and Markdown valid
- Do not count transfers as spending
- Do not convert dates to local time again — the script already did
