---
name: debt_tracker
description: Track money owed to and from the user
version: 0.2.0
author: hushmoney
metadata:
  hermes:
    tags: [Debts, Tracking]
    category: hushmoney
    requires_tools: [terminal]
---

# Debt Tracker

## When to Use

Triggered by natural language about shared money:
- "I paid dinner for João, he owes me $35"
- "I owe Laura COP 12,000 for lunch"
- "João paid me back"
- "¿cuánto me debe Juan?" / "show my debts"

## Procedure

### Record a debt

Extract: **person**, **amount**, **currency** (COP if unspecified), **direction**
(`they_owe` or `i_owe`), **description** (optional).

```
python3 /root/.hermes/skills/hushmoney/debt_tracker/scripts/record_debt.py \
  --person "<name>" \
  --amount <amount> \
  --currency <COP|USD|...> \
  --direction <they_owe|i_owe> \
  [--description "<context>"]
```

Confirm: "✅ João owes you $35 USD (dinner)"

### Settle a debt

1. List open debts for that person:
   ```
   python3 /root/.hermes/skills/hushmoney/debt_tracker/scripts/get_active_debts.py \
     --person "<name>"
   ```
2. If one open debt → settle directly. If multiple → show list, ask which one.
3. Settle:
   ```
   python3 /root/.hermes/skills/hushmoney/debt_tracker/scripts/settle_debt.py \
     --id <debt_id>
   ```
   Or settle all with a person:
   ```
   python3 /root/.hermes/skills/hushmoney/debt_tracker/scripts/settle_debt.py \
     --person "<name>" --all
   ```
4. Confirm: "✅ Settled — João no longer owes you."

### Show debt summary

```
python3 /root/.hermes/skills/hushmoney/debt_tracker/scripts/get_active_debts.py
```

Format:
```
💸 *Deudas activas*

*Te deben:*
  • João — $35 USD (dinner, hace 3 días)
  • María — COP 25,000 (taxi, hoy)

*Debes:*
  • Laura — COP 12,000 (almuerzo, ayer)
```

If no debts: "No hay deudas activas. 🎉"

## Pitfalls

- Don't confuse bank transfer notifications with debts — those are in `transactions`.
- Always confirm before settling.
- Default currency to COP when conversation is in Spanish and no symbol is given.
