# Cloudflare Email Worker

Receives mail forwarded to a HushMoney address and POSTs `{ from, subject, body }` to the Forwarder.

## Prerequisites

- Node.js 20+
- A Cloudflare account with [Email Routing](https://developers.cloudflare.com/email-routing/) enabled on the zone that serves `@hushmoney-deploy.dev` (or your own domain)
- The Forwarder URL that will accept `POST /channels/email`

## Install

```bash
cd config/cloudflare
npm install
npx wrangler login
```

## Configure

1. In `wrangler.toml`, set `EMAIL_WEBHOOK_URL` to the Forwarder email endpoint (replace the `REPLACE_ME` placeholder).
2. Set the shared secret on the deployed Worker (same value as the forwarder's `EMAIL_WEBHOOK_SECRET`):

```bash
npx wrangler secret put EMAIL_WEBHOOK_SECRET
```

For **local testing only**, do not use that command — put the value in `config/cloudflare/.env` (or `.dev.vars`) next to `wrangler.toml`. Wrangler loads it during `wrangler dev` and never deploys it. See the [local check](#local-check-wrangler-dev) section.

The Worker does not POST if the URL is still the placeholder or the secret is missing.

## Deploy

```bash
cd config/cloudflare
npx wrangler deploy
```

Then in the Cloudflare dashboard: **Email Routing → Routes** (or destination addresses) → send matching addresses to the Worker named `hushmoney-email`.

Gmail: add a forwarding rule (and filter) to that address. See `docs/architecture.md`.

## Payload sent to the Forwarder

```http
POST /channels/email
Content-Type: application/json
Authorization: Bearer <EMAIL_WEBHOOK_SECRET>
```

```json
{
  "from": "alertasynotificaciones@ayn.notificacionesbancolombia.com",
  "subject": "Alertas y Notificaciones",
  "body": "Bancolombia: Compraste $47.350,00 en Rappi ..."
}
```

`body` is the decoded `text/plain` part (via PostalMime). Empty bodies are dropped and not sent.

## Local check (`wrangler dev`)

```bash
cd config/cloudflare
npx wrangler dev
```

### Setting the secret locally

`wrangler dev` does not read deployed secrets. Provide `EMAIL_WEBHOOK_SECRET` locally in one of these ways (all local-only, none deployed):

- **`.env` next to `wrangler.toml`** (what this repo uses) — gitignored:
  ```bash
  EMAIL_WEBHOOK_SECRET=TESTING_SECRET
  ```
- **`.dev.vars` next to `wrangler.toml`** — Wrangler's classic file; if present it takes exclusive precedence over `.env`. Must be added to `.gitignore` yourself since we use most commonly `.env`.
- **One-off on the command line**:
  ```bash
  npx wrangler dev --var EMAIL_WEBHOOK_SECRET:TESTING_SECRET
  ```

Do **not** put the secret in `wrangler.toml` `[vars]` — those values are committed and uploaded in plaintext by `wrangler deploy`.

Point a listener at `EMAIL_WEBHOOK_URL`, then POST a raw RFC 5322 message (must include `Message-ID`) to Wrangler’s local email endpoint:

```bash
curl --request POST "http://localhost:8787/cdn-cgi/local/email" \
  --url-query "from=alertasynotificaciones@ayn.notificacionesbancolombia.com" \
  --url-query "to=user@hushmoney-deploy.dev" \
  --data-binary "@../../tests/fixtures/emails/bancolombia/compra_debito.eml"
```

If the fixture has no `Message-ID`, add one before sending. Confirm the listener received the JSON and the `Authorization` header — not the raw email in Worker logs.
