---
name: export
description: Export the user's transactions to a CSV file sent on Telegram
version: 0.1.0
author: hushmoney
metadata:
  hermes:
    tags: [Export, Reporting]
    category: hushmoney
    requires_tools: [terminal]
---

# Export

## When to Use

The user asks for their transactions as a file:
- "hermes export", "exportar", "export this month", "exportar este mes"
- "hermes export this week", "exportar esta semana"
- "hermes export 2026-09", "exportar septiembre"
- "exporta del 1 al 15 de octubre"

## Procedure

### Step 1 — Determine period

| User says | Flag |
|---|---|
| no qualifier, "this month", "este mes" | `--period month` |
| "this week", "esta semana" | `--period week` |
| a month: "2026-09", "septiembre", "last month", "el mes pasado" | `--month YYYY-MM` |
| a date range | `--from YYYY-MM-DD --to YYYY-MM-DD` |

A month name without a year means the most recent one that is not in the future.

Run:
```
python3 /root/.hermes/skills/hushmoney/export/scripts/export_csv.py <flag>
```

### Step 2 — Send the file

Parse the JSON.

If `path` is null:
> No hay transacciones para [period].

Otherwise reply with one short line plus the `MEDIA:` tag on its own line, using the exact
`path` from the JSON:

```
📎 Tus transacciones de [period] (N movimientos)
MEDIA:/tmp/hushmoney_exports/hushmoney_2026-10.csv
```

The Hermes gateway turns the `MEDIA:` line into a Telegram document upload and hides
the tag from the message text.

## CSV format

```
date,merchant,amount,currency,category,transaction_type,account,channel
2026-10-15T14:32:00Z,El Corral,-35000,COP,food,debit,Bancolombia ****1234,sms
2026-10-15T18:00:00Z,,4500000,COP,transfers,transfer_in,Bancolombia ****1234,email
```

- `amount` is negative for spending and positive for income (`transfer_in`, `credit`)
- Dates are UTC, oldest first
- No internal ids, message hashes or card numbers

## Pitfalls

- Never write the CSV yourself or paste its rows into the chat — always send the file.
- Do not put the `MEDIA:` line inside a code block or quote; the gateway ignores it there.
- Use the `path` exactly as returned; do not guess or rebuild it.
- Each run deletes the previous export, so only send the path from the latest run.
