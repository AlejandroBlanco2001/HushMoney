# Bancolombia Email Format Notes

Observations derived from real Bancolombia notification emails. Anyone writing the
sanitizer for this bank must read this first.

## Sender Addresses

Bancolombia uses **two different subdomains** for the same notification type:

| Subdomain | Observed on |
|---|---|
| `alertasynotificaciones@ayn.notificacionesbancolombia.com` | Debit card purchases (`compra_debito`) |
| `alertasynotificaciones@an.notificacionesbancolombia.com` | Transfers, payments, everything else |

Both must be treated as trusted Bancolombia senders. The sanitizer should accept either.
Do not hardcode only one.

## Amount Format

Bancolombia uses **Colombian/European number format**: `.` as thousands separator, `,` as decimal.

```
$47.350,00   →  47350.00 COP
$250.000,00  →  250000.00 COP
$1.500.000,00 → 1500000.00 COP
```

The sanitizer must parse this format specifically — a standard float parser will misread it.
All amounts are COP unless a currency symbol or code explicitly says otherwise (rare).

## Date Formats

Bancolombia uses **two different date formats** with no apparent rule for which one appears:

| Format | Example | Notes |
|---|---|---|
| `DD/MM/YYYY a las HH:MM` | `15/09/2026 a las 12:43` | Full 4-digit year, no seconds |
| `DD/MM/YY a las HH:MM` | `14/09/26 a las 08:06` | 2-digit year — assume 20XX |
| `DD/MM/YYYY HH:MM:SS` | `14/09/2026 03:43:19` | Full year with seconds, no "a las" |

All times are **Colombia Standard Time (UTC-5)**. No daylight saving. Convert to UTC when
building the clean payload.

## Fields to Strip

| Field | Pattern example | Notes |
|---|---|---|
| Debit card number | `T.Deb *1234` | Last 4 digits only; strip the whole token |
| Account number (source) | `tu cuenta *1234` | Strip the whole phrase |
| Account number (destination) | `la cuenta *00001111222` | Longer mask; still strip |
| Product number | `tu producto 1234` | Used in Botón Bancolombia payments |
| "Llave" key | `la llave 000000` / `la llave 0000000000` / `la llave @SYNTHETICUSER` | Freeform — can be cédula, phone number, or @username. Strip from `la llave ` to next date marker. See `sms/bancolombia/FORMAT_NOTES.md`. |
| Recipient/sender name | `MARIA GARCIA,` | Appears at message start for transfers; strip |
| Transfer counterparty | `de JUAN PEREZ` | Sender name in incoming transfers; strip |
| Phone numbers | `6045109095`, `018000931987`, `018000912345` | Support lines; strip |
| Promotional text | `Con llaves es de una y gratis.` | Filler; strip entire closing sentence |
| Balance | not seen yet | Strip if it ever appears — see SYNTHETIC_DATA.md |

## Merchant / Counterparty Extraction

| Template | What to extract | Notes |
|---|---|---|
| `Compraste $X en MERCHANT con tu T.Deb` | `MERCHANT` | Normalize to uppercase |
| `Pagaste $X a MERCHANT desde tu producto` | `MERCHANT` | May include legal suffixes like `SAS`, `S.A.S.` |
| `Transferiste $X desde tu cuenta ... a la cuenta` | absent | Destination is an account number, not a merchant — strip, leave `merchant` field out of payload |
| `recibiste una transferencia de PERSON_NAME` | absent | Counterparty is a person name — strip, leave `merchant` field out of payload |

## Transaction Type Mapping

| Spanish verb in message | `transaction_type` value |
|---|---|
| `Compraste` | `debit` |
| `Pagaste` | `payment` |
| `Transferiste` | `transfer_out` |
| `recibiste una transferencia` | `transfer_in` |
| `Retiraste` *(not yet observed)* | `cash` |

## Scenarios Still Needed

These transaction types exist in Bancolombia but no sample has been provided yet:

- `retiro_atm` — ATM cash withdrawal (`Retiraste`)
- `compra_credito` — credit card purchase (different card label: `T.Cred`)
- `compra_con_otp` — purchase that includes an OTP (observed in some international transactions)
- `pago_servicio` — utility payment via PSE
- `recarga_nequi` — Nequi top-up (may come from a different sender address)

Add fixtures here when samples become available.
