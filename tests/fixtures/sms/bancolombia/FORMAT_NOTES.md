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

## "Llave" — See BREB.md

The llave is a Bre-B system alias, not a Bancolombia-specific field. It can be a cédula,
a phone number, an email, or an alphanumeric code. Stripping it is a global sanitizer
rule that applies to all banks.

See `tests/fixtures/BREB.md` for the full definition, the four key types, the recommended
regex pattern, and synthetic placeholders to use across fixtures.

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
