# Telegram intake

The Telegram forwarder accepts bank notifications from one private user chat.
It sanitizes them before dispatching the clean transaction to Hermes. Hermes
continues to own the bot token, register the webhook and send replies.

```text
Telegram -> public HTTPS /telegram -> telegram-forwarder
                                       | known bank text -> sanitizer -> Hermes /gateway
                                       | exact command   -> Hermes internal /telegram
                                       | other input     -> discard
```

There is no second poller. Hermes runs in webhook mode and registers the public
URL pointing at the forwarder, not at its own internal webhook server.
The adapter does not need IMAP credentials or the bot token.

## Supported messages

- Forwarded or pasted Bancolombia notifications supported by the sanitizer.
  They retain `channel: sms`, matching the current SMS payload contract.
- Exact, unforwarded `/start`, `/help`, `/status`, `/new` and `/stop` commands.
  No arguments, surrounding whitespace or `@bot` suffixes are accepted.
  Commands are rebuilt with only routing IDs, the command text and a synthetic
  display name. Quoted bank messages and user names never reach Hermes.
- Other text, unknown bank formats, command arguments, attachments, edits,
  callbacks and non-private chats are ignored. Free-form conversations,
  interactive setup and bank-learning confirmations need a separate routing
  contract and are not supported by this MVP adapter.

Both the sender ID and private chat ID must equal `TELEGRAM_CHAT_ID`. A relay must
deliver a text message from that user; messages sent by bots are ignored.
Forwarded commands are never executed.

## Run with Docker Compose

1. Set the existing bot credentials and `TELEGRAM_CHAT_ID` in `.env`.
   Generate `TELEGRAM_WEBHOOK_SECRET` with `openssl rand -hex 32`.
2. Set `TELEGRAM_WEBHOOK_URL` to an HTTPS address ending exactly in `/telegram`.
   This environment variable is required by the upstream Hermes webhook API.
   Forwarder behavior, listen address, timeouts and internal destinations live
   in `config/hermes.yaml` under `forwarder.telegram`.
3. Configure your HTTPS ingress to send `/telegram` to the forwarder on port
   9000. The supplied Compose override binds it to `127.0.0.1:9000` for a
   host reverse proxy. A containerized ingress should use
   `telegram-forwarder:9000` on the Docker network instead.
   Keep Hermes port 8443 private and preserve the
   `X-Telegram-Bot-Api-Secret-Token` header. Do not log request bodies or secrets.
4. Start the services:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.telegram.yml \
     up -d --build hermes telegram-forwarder
   ```

   To also run the existing email poller, configure IMAP and include the
   `forwarder` service in the command.

Hermes and the adapter use the same webhook secret. Hermes registers the public
URL with Telegram and listens internally on port 8443 with the same `/telegram`
path. A deployment-provided HTTPS hostname works; this does not require an email
domain or Cloudflare Email Workers. Never run another gateway polling the same
bot while webhook mode is enabled.

The override is opt-in. Running the original Compose file alone retains the
existing runtime. Stop `telegram-forwarder` and recreate Hermes without the
override to return to its original polling mode.

## Verification

Run the automated checks from the repository root:

```bash
bash scripts/run_tests.sh
uv run --project forwarder ruff check forwarder/src/forwarder/channels \
  forwarder/src/forwarder/hermes.py forwarder/tests/test_telegram*.py
```

The synthetic update in `tests/fixtures/telegram/forwarded_purchase.json` follows
the Telegram Bot API shape and contains no real personal data. Tests send it
through the HTTP endpoint and real sanitizer, then inspect requests to a mock
Hermes transport. They also cover command routing, authentication, unauthorized
chats, metadata removal, malformed bodies and failed dispatches.

After deploying, send `/help` from the configured user's private chat and check
that Hermes replies. Paste the synthetic Bancolombia SMS from
`tests/fixtures/sms/bancolombia/compra_debito.txt` and verify that Hermes receives
the expected clean transaction. Send a message from a different account and
verify it produces neither a transaction nor a reply. Do not inspect raw
financial message bodies in production logs.

Valid updates receive HTTP 200 even if Hermes is unavailable: the message is
dropped with a fixed log message, without a retry queue. Telegram itself may
redeliver updates after a connection failure; this stateless adapter does not
provide exactly-once delivery.

## Upstream contract

The routing uses the existing project's `/gateway` clean-payload endpoint and
the upstream Hermes Telegram webhook server. Verify both endpoints on the
deployed Hermes image before enabling real traffic.

- [Telegram webhook authentication and update schema](https://core.telegram.org/bots/api#setwebhook)
- [Hermes webhook mode](https://github.com/NousResearch/hermes-agent/blob/0b10b9f8155a7ecadd8c540b87712c791b5c8ac9/website/docs/user-guide/messaging/telegram.md#webhook-mode)
- [Hermes implementation inspected for this adapter](https://github.com/NousResearch/hermes-agent/blob/0b10b9f8155a7ecadd8c540b87712c791b5c8ac9/plugins/platforms/telegram/adapter.py)
