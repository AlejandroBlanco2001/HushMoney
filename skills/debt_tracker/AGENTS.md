# debt_tracker skill

Keeps the list of people the user owes money to and people who owe the user. Debts are
created from what the user says on Telegram; they can be settled by the user or linked
to a tracked bank transfer. No forwarder involved for creating debts.

## Inputs

Natural-language messages from the user:
```
"I paid dinner for João, he owes me $35"
"le presté 50 mil a Ana"
"le debo 20k a mi hermano"
"Ana ya me pagó"
```

Or a transaction id from `expense_tracker` when a `transfer_in` / `transfer_out` is stored.

## Three flows

**Record** — extract person, amount, direction and an optional description:

| User says | `direction` |
|---|---|
| "X me debe", "le presté a X", "pagué por X" | `they_owe` |
| "le debo a X", "X me prestó", "X pagó por mí" | `i_owe` |

Amounts are parsed by the script (`35000`, `35.000`, `35 mil`, `35k`, `$35.000,50`);
currency defaults to COP.

**List / settle** — show active debts grouped by person with a net balance, or settle:
- everything with a person in one direction
- a partial amount (applied to the oldest debts first; a partly covered debt keeps
  its row with the remaining amount)
- one specific debt by short id

**Match transfer** — after a transfer is stored, look for open debts with the same
amount and currency:

```
transfer_in  → debts where someone owes the user (they_owe)
transfer_out → debts the user owes (i_owe)
```

Transfers carry no counterparty name (the sanitizer strips it), so matching is by amount
only. Hermes **asks** the user before settling:

```
Hermes → Telegram: "Recibí una transferencia de $185.000. ¿Es Ana pagándote?"
User: "sí"
Hermes: settles the debt with settled_by_transaction_id = <transfer id>
```

## Tools this skill uses

### `add_debt`
```sql
INSERT INTO debts (id, person, amount, currency, direction, description, created_at)
VALUES (?, ?, ?, ?, ?, ?, ?);
```

### `get_active_debts`
```sql
SELECT * FROM debts WHERE settled_at IS NULL [AND person = ? COLLATE NOCASE]
ORDER BY created_at;
```
Net per person: `they_owe` counts positive, `i_owe` negative.

### `settle_debt`
```sql
-- full
UPDATE debts SET settled_at = ?, settled_by_transaction_id = ? WHERE id = ?;
-- partial
UPDATE debts SET amount = ? WHERE id = ?;
```

### `match_transfer`

Reads the transaction and the active debts in the matching direction; returns up to 3
candidates (single debt with the same amount, or a person's total with the same amount).

## What NOT to do

- Do not settle a debt from a transfer without the user's explicit "sí"
- Do not store phone numbers, account numbers or Bre-B keys in `description`
- Do not mix currencies — a COP payment never settles a USD debt
- Do not create a new person for a spelling variant ("Joao" vs "João") — reuse the
  existing name when one is clearly the same person
