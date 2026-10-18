# Bre-B — Sistema de Pagos Inmediatos de Colombia

**Bre-B** is Colombia's national instant interoperable payment network, operated by the
Banco de la República. It went into full interoperable operation in October 2025.
Any bank, cooperative, digital wallet, or fintech participating in Bre-B can send and
receive transfers to any other participant in under 20 seconds, 24/7.

Reference: [Banco de la República — Bre-B](https://www.bancolombia.com/open-data/interoperabilidad-bre-b)

## Why This Matters for the Sanitizer

The "llave" (key) is the universal alias a user registers to receive Bre-B transfers.
It appears in transfer notifications from **every Bre-B participant** — not just Bancolombia.
As more banks adopt Bre-B (all major Colombian banks are either live or onboarding),
`la llave <value>` will appear in notifications from:

- Bancolombia / Nequi
- Davivienda
- BBVA Colombia
- Nu (Nubank Colombia)
- Rappipay
- Banco de Bogotá
- Scotiabank Colpatria
- Any other participant

**Llave stripping is a global sanitizer rule, not a bank-specific one.**
It must be implemented once at the sanitizer level and will apply to all banks automatically.

## The Four Key Types

Bre-B allows users to register exactly four types of llave:

| Type | Format | Example (synthetic) | Notes |
|---|---|---|---|
| Cédula de ciudadanía | 10 digits | `0000000000` | Colombian national ID; most common |
| Número de celular | 10 digits, starts with `3` | `3000000000` | Colombian mobile number |
| Correo electrónico | Standard email | `user@example.com` | Full email address as alias |
| Código alfanumérico | Letters + digits, user-defined | `@SYNTHETICUSER` or `ABC12345` | May or may not start with `@` |

**A cédula and a phone number are both 10 digits and cannot be reliably distinguished
by format alone.** The sanitizer must not try to identify which type the llave is —
it must strip the entire value unconditionally.

## How It Appears in Notifications

The phrase is always `conectada a la llave <value>` followed by a date marker:

```
en tu cuenta *1234 conectada a la llave 0000000000 el 14/09/26 a las 08:06
en tu cuenta *1234 conectada a la llave 3000000000 el 14/09/26 a las 08:06
en tu cuenta *1234 conectada a la llave user@example.com el 14/09/26 a las 08:06
en tu cuenta *1234 conectada a la llave @SYNTHETICUSER el 14/09/26 a las 08:06
```

The value always ends before `el DD/MM` — use that as the right boundary.
The value is always a single token (no spaces inside it).

**Recommended sanitizer pattern:**

```python
# Strip everything between "la llave " and the next date marker "el \d{2}/\d{2}"
re.sub(r'la llave \S+(?=\s+el\s+\d{2}/\d{2})', 'la llave [REDACTED]', text)
```

## Synthetic Fixture Placeholders

Use these across all bank fixtures to cover each llave type:

| Llave type | Placeholder to use in `.txt` / `.eml` fixtures |
|---|---|
| Cédula | `0000000000` |
| Phone number | `3000000000` |
| Email | `user@example.com` |
| Alphanumeric | `@SYNTHETICUSER` |

Rotate through all four types across scenarios so the sanitizer is tested against each.
A single bank with four `transferencia_recibida` variants (one per llave type) is enough
to validate the pattern works universally.

## Participating Banks — Fixture Priority

Add `transferencia_recibida` fixtures for each bank as samples become available.
The llave stripping logic will be the same; what differs is the surrounding sentence
structure and the bank's notification template.

| Bank | Bre-B status | Fixtures |
|---|---|---|
| Bancolombia | Live | 4 email + 4 SMS (llave: `@SYNTHETICUSER`) |
| Nequi | Live (Bancolombia subsidiary) | pending |
| Davivienda | Live | pending |
| Nu Colombia | Live | pending |
| BBVA Colombia | Live | pending |
| Rappipay | Live | pending |
| Banco de Bogotá | Onboarding | pending |

Sources:
- [Bre-B Wikipedia](https://es.wikipedia.org/wiki/Bre-B)
- [Nequi — Guía Bre-B](https://www.nequi.com.co/blog/bre-b-guia-rapida-del-sistema-de-pagosinteroperables-e-inmediatos-en-colombia)
- [Nu Colombia — Llaves](https://blog.nu.com.co/bre-b-paga-con-tus-llaves-en-segundos/)
- [Getmeru — Qué es Bre-B](https://getmeru.com/blog/fintech/que-es-bre-b-como-funciona/)
