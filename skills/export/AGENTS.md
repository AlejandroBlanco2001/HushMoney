# export skill

Sends the user their transactions as a CSV attachment on Telegram, so they can open
them in Excel or Google Sheets.

## Inputs

A user message on Telegram:
```
"hermes export"                 → current month
"hermes export this week"       → current week (Monday to now)
"hermes exportar 2026-09"       → that whole month
"exporta del 1 al 15 de octubre" → explicit range
```

## Flow

1. Map the message to `--period week|month`, `--month YYYY-MM` or `--from` / `--to`
2. Run `export_csv.py` — it writes `/tmp/hushmoney_exports/hushmoney_<period>.csv`
   and prints `{"path", "count", "period", "from", "to"}`
3. Reply with a one-line caption and `MEDIA:<path>`; the Hermes gateway uploads the
   file with Telegram's `sendDocument`

## Temporary files

The upload happens after the agent's turn ends, so the script cannot delete its own
output. Instead every run deletes the previous `hushmoney_*.csv` before writing the new
one: at most one export sits in `/tmp/hushmoney_exports` at any time.

## What goes in the file

| Column | Source |
|---|---|
| `date` | `transactions.date` (UTC) |
| `merchant` | `transactions.merchant` (empty for transfers) |
| `amount` | negative for spending, positive for `transfer_in` / `credit` |
| `currency`, `category`, `transaction_type`, `channel` | `transactions` |
| `account` | bank name + `accounts.masked_number` |

Text cells starting with `=`, `+`, `-` or `@` are prefixed with `'` so a merchant name
from a bank notification can never run as a spreadsheet formula.

## What NOT to do

- Do not include ids, `message_hash` or card numbers in the export
- Do not paste the transactions into the chat instead of sending the file
- Do not keep exports around — they hold the user's financial history
