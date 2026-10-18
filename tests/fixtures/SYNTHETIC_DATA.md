# Synthetic Test Data

All files in this directory are **synthetic**. They are constructed to match the format and structure of real bank notifications but contain no real financial data, no real account numbers, no real OTPs, and no real personal information.

Do not add real bank messages here, even with the sensitive parts replaced. Construct samples from scratch using the templates and rules below.

---

## Purpose

These fixtures exist to test two things:

1. **Sanitizer correctness** — does the sanitizer strip the right fields from a given bank's message format? Each fixture pairs a raw message (`.eml` or `.txt`) with the expected clean payload (`.expected.json`). If the sanitizer output does not match the expected JSON, the test fails.

2. **Channel parsing** — does the email or Telegram channel adapter correctly extract the message body and metadata before passing it to the sanitizer?

They are not used to test categorization (that is the job of `skills/categorizer/evals/golden.jsonl`).

---

## Directory Structure

```
tests/fixtures/
├── SYNTHETIC_DATA.md        ← you are here
├── emails/
│   ├── bancolombia/
│   │   ├── <scenario>.eml
│   │   └── <scenario>.expected.json
│   ├── davivienda/
│   ├── nequi/
│   ├── bbva/
│   └── rappipay/
└── sms/
    ├── bancolombia/
    │   ├── <scenario>.txt
    │   └── <scenario>.expected.json
    ├── davivienda/
    └── nequi/
```

### Scenario naming

Name files after the transaction type, not the bank:

```
compra_debito          purchase on debit card
compra_credito         purchase on credit card
retiro_atm             ATM cash withdrawal
transferencia_enviada  outgoing transfer
transferencia_recibida incoming transfer
pago_servicio          utility / service payment
recarga                top-up (Nequi, Rappipay)
compra_con_otp         purchase that includes an OTP in the message
saldo_insuficiente     declined transaction (should be ignored by sanitizer)
```

---

## Rules for Generating Synthetic Messages

### Amounts

- Use plausible Colombian peso amounts: between $5,000 and $5,000,000 COP
- Format exactly as the bank formats it — some use `.` as thousands separator, some use `,`
- Do not use round numbers like $100,000 — use $97,350 or $204,800

### Account and card numbers

- Always use `**** 1234` or `****1234` — never a real or sequential number
- If the bank shows only the last 4 digits, use `1234`
- If the bank shows a masked full number, use `**** **** **** 1234`

### OTPs and verification codes

- Always use `000000` for 6-digit OTPs
- Always use `00000000` for 8-digit OTPs
- Never use a real or plausible OTP — `000000` is unmistakably synthetic

### Merchants

Use real merchant names that operate in Colombia — the sanitizer should not strip merchant names, so using real ones verifies that. Good choices:

| Category | Merchants |
|---|---|
| Groceries | EXITO, JUMBO, CARULLA, D1, ARA, RAPPI |
| Transport | UBER, CABIFY, TRANSMILENIO, PICAP |
| Dining | MCDONALD'S, CREPES & WAFFLES, EL CORRAL |
| Fuel | TERPEL, BIOMAX, PRIMAX |
| Pharmacy | DROGAS LA REBAJA, FARMATODO, CRUZ VERDE |
| Tech | CLARO, MOVISTAR, ETB, NETFLIX |

### Dates and times

- Use realistic past dates, never today's date (avoids test flakiness)
- Use the format the specific bank uses — some use `DD/MM/YYYY`, some use `DD-MMM-YYYY`
- Reference date for all fixtures: **2026-09-15** (use variations around this)

### Personal names

- Never use a real name
- Use `MARIA GARCIA` (sender) or `JUAN PEREZ` (recipient) as the two generic names
- Only include names if the real bank message format includes them

### Balance figures

- Never include current balance in the expected clean payload — balance is not a transaction event
- If the bank message includes the balance, the sanitizer must strip it
- Use `$X,XXX,XXX` as the synthetic balance if needed in the raw message

---

## Expected Clean Payload Schema

Every `.expected.json` file must conform to this schema exactly:

```json
{
  "amount": 97350.00,
  "currency": "COP",
  "merchant": "EXITO",
  "date": "2026-09-15T14:32:00Z",
  "transaction_type": "debit",
  "account_type": "checking",
  "channel": "email"
}
```

| Field | Type | Allowed values |
|---|---|---|
| `amount` | float | positive number, in the currency's minor unit |
| `currency` | string | `"COP"`, `"USD"` — use `"COP"` for all Colombian bank fixtures |
| `merchant` | string | normalized uppercase merchant name, no punctuation |
| `date` | string | ISO 8601 UTC |
| `transaction_type` | string | `"debit"`, `"credit"`, `"cash"`, `"transfer_out"`, `"transfer_in"`, `"payment"`, `"top_up"` |
| `account_type` | string | `"checking"`, `"savings"`, `"credit"`, `"digital_wallet"` |
| `channel` | string | `"email"`, `"sms"`, `"telegram"` |

If the sanitizer cannot determine a field from the raw message, omit it from the expected JSON — the test will assert the field is absent from the output, not that it is null.

---

## Adding a New Bank

1. Create a subdirectory under `emails/` and/or `sms/` with the bank's slug (lowercase, no spaces)
2. Add at least these four scenarios before considering the bank covered:
   - `compra_debito` — most common transaction type
   - `retiro_atm` — cash withdrawal (triggers the cash operation flow)
   - `compra_con_otp` — verifies OTP stripping works for this bank's format
   - `transferencia_enviada` — outgoing transfer (different sanitizer path)
3. For each scenario, write the raw message first, then derive the expected JSON from it manually — do not generate the expected JSON from the sanitizer output (that defeats the purpose)
4. Add the bank to the table below

---

## Banks Covered

| Bank | Email fixtures | SMS fixtures | Notes |
|---|---|---|---|
| Bancolombia | pending | pending | Largest bank in Colombia; highest priority |
| Nequi | pending | pending | Digital wallet owned by Bancolombia; app notifications forwarded via Telegram |
| Davivienda | pending | pending | |
| BBVA Colombia | pending | pending | Uses international BBVA format with Spanish copy |
| Rappipay | pending | pending | Digital wallet; notifications via app/email |

Update this table when fixtures are added. Change `pending` to the number of scenarios covered (e.g. `4 scenarios`).

---

## What the Sanitizer Must Always Strip

Regardless of bank or channel, these must never appear in the clean payload or in any log:

- OTPs and verification codes
- Full or partial account numbers (including last-4 patterns like `*1234`)
- Card numbers in any format
- Current balance figures
- Full recipient or sender names
- URLs included in the bank message (tracking links, portal links)
- Any string matching an IBAN or routing number pattern

If you are writing a fixture and you are unsure whether a field should be stripped, err on the side of stripping it and add a comment in the raw message file.
