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

1. Map the trigger or question to a period: `--period day|week|month` with
   `--offset` (0 = current, -1 = previous), or an explicit `--from` / `--to`
2. Run `query_transactions` — it computes the totals and renders the message
3. Scheduled or general question → send the rendered `text` as is
4. Specific question → answer in one or two sentences using only numbers from the JSON

## What counts as what

| Bucket | `transaction_type` |
|---|---|
| Spending | `debit`, `payment`, `cash` |
| Income | `transfer_in`, `credit` |
| Transfers out (reported separately) | `transfer_out` |

## Time zone

Periods are the user's **local** days (`user_settings.timezone`, default
`America/Bogota`, UTC-5). Transactions are stored in UTC, so a purchase at
Sunday 22:30 Bogotá (`Monday 03:30Z`) belongs to Sunday.

## Comparison with the previous period

`delta_pct` compares against the previous period **of the same length so far** —
Monday–Wednesday vs. last Monday–Wednesday — so mid-period comparisons are fair. It is
`null` when the previous period had no spending.

## Tools this skill uses

### `query_transactions`
```sql
SELECT * FROM transactions WHERE date >= ? AND date < ? ORDER BY date;
SELECT direction, currency, SUM(amount) FROM debts
WHERE settled_at IS NULL GROUP BY direction, currency;
```

Returns totals, spending by category with share, top 5 merchants, largest purchase,
pending clarifications, recurring merchants, active debt totals, and `text` — the
message rendered from `templates/daily.md`, `weekly.md` or `monthly.md`, with
category labels from `assets/category_labels.json`.

## What NOT to do

- Do not compute or re-add totals in the model
- Do not rewrite or "improve" the rendered `text` — it keeps numbers exact and Markdown valid
- Do not count transfers as spending
- Do not convert dates to local time again — the script already did
