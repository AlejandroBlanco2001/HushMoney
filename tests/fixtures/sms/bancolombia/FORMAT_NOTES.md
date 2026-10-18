# Bancolombia SMS Format Notes

Read alongside `emails/bancolombia/FORMAT_NOTES.md` — most rules there apply here too.
This file covers only the differences.

## Body Format Is Identical to Email

Bancolombia uses the **same message template** for both email bodies and SMS. This means
the sanitizer's core regex patterns for Bancolombia can be shared between the email and
SMS channel adapters. The channel adapter's job is to extract the text; the sanitizer's
job is to parse it — the parsing logic is the same regardless of channel.

The `channel` field in the clean payload reflects the **origin** (`"sms"`), not the
delivery transport (Telegram bot). The Telegram adapter should detect the Bancolombia
SMS pattern and set `channel: "sms"` in the payload it hands to the sanitizer.

## "Llave" Is Freeform — Not a Fixed Format

The Bancolombia "llave" (transfer key) is user-defined and can be any of:

| Form | Example | Synthetic placeholder |
|---|---|---|
| Colombian cédula (10 digits) | `1001820876` | `0000000000` |
| Phone number (10 digits, may start with 3) | `3001234567` | `3000000000` |
| Username / handle | `@ISAB1010` | `@SYNTHETICUSER` |
| Short numeric code (6 digits) | `882910` | `000000` |

Because the format is freeform, the sanitizer **cannot use a length or character-class
pattern**. It must match everything between `la llave ` and the next known sentence
boundary (a space followed by `el`, `el`, or end of that clause):

```
la llave (\S+)(?=\s+el\s|\s+el\s)
```

Or more defensively: strip from `la llave ` to the next date marker (`el DD/MM`).

In synthetic fixtures, vary the llave form across scenarios to exercise all paths:
- `transferencia_recibida` → use `@SYNTHETICUSER` (username form)
- Future `transferencia_recibida_cedula` → use `0000000000`
- Future `transferencia_recibida_phone` → use `3000000000`

## One Raw Message, No Headers

SMS fixtures are plain `.txt` files containing only the message body.
There are no From/Subject/Date headers — those are email-only.
The timestamp comes from inside the message text itself.

## Observed Quirk: Missing Leading Character

One provided sample started with `ancolombia:` instead of `Bancolombia:`, suggesting
the leading `B` was dropped — possibly a display artifact in the SMS app, an SMS
concatenation issue, or a copy-paste error. The sanitizer should not be fragile to this,
but no fixture for this edge case has been created yet. Add one if it is confirmed to
occur in practice.

## Coverage

| Scenario | File | Notes |
|---|---|---|
| `compra_debito` | `compra_debito.txt` | Uber Rides, debit card |
| `transferencia_recibida` | `transferencia_recibida.txt` | Llave is 10-digit cédula |
| `transferencia_enviada` | `transferencia_enviada.txt` | Same format as email |
| `pago_boton` | `pago_boton.txt` | Botón Bancolombia / PSE |

Still needed: `retiro_atm`, `compra_credito`, `compra_con_otp`.
