# ADR-0005 — Three transports into Hermes

- **Status:** Accepted
- **Date:** 2026-10-24

## Context

The forwarder has to get information to the Hermes agent in three distinct situations,
and they genuinely differ in shape:

1. A notification parsed into a structured transaction.
2. A notification nothing could parse, which needs an interactive LLM conversation.
3. A raw SMS that arrived on the user's phone and needs to enter the pipeline at all.

A reader seeing three different "send to Hermes" mechanisms in the code reasonably asks
"why isn't this one path?" This ADR records why they are separate.

## Decision

Keep **three transports**, each matched to its payload:

1. **Structured → gateway HTTP.** `hermes.dispatch` / `dispatch_async` POST a
   `CleanPayload` (JSON) to `gateway_server.py:/gateway`. This is the happy path for a
   successfully parsed transaction; the gateway stores + categorizes + notifies.
2. **Unparseable → synthesized Telegram message.** `UnmatchedHandler` wraps the redacted
   text in a `[bank_learning]` envelope and POSTs it to `hermes_webhook_url` as a
   *user message*, so Hermes runs the `bank_learning` skill conversationally. It must
   look like user input because the outcome is an interactive dialog, not a data write.
3. **SMS origin → MTProto inject.** `scripts/sms_listener.py` watches the user's Telegram
   "Saved Messages" (where an iPhone Shortcut drops incoming SMS) and, for interactive
   flows, injects text to the bot via `app.send_message` so Hermes picks it up by
   polling. This bridges the phone→Telegram→Hermes gap that neither HTTP path covers.

The distinction is **data vs. conversation vs. origin-bridge**: structured data takes the
typed HTTP path; anything that must become a chat turn takes a message path.

## Consequences

- **Good:** each payload uses the simplest mechanism that fits; the structured path stays
  typed and testable while the interactive path reuses Telegram's existing chat UX.
- **Bad:** three places construct Telegram-update JSON or set gateway auth headers, with
  duplicated URL/secret handling across `hermes.py`, `learning/unmatched.py`, and
  `gateway_server.py`. A thin `HermesClient` could centralize auth and envelope building
  without collapsing the three semantics.
- **Bad:** the synthesized-message path depends on the forwarder faithfully mimicking a
  Telegram update shape; drift in Telegram's format or the webhook validator
  (`channels/telegram._build_message`) can silently break learning.
- **Bad:** more transports = more failure modes to reason about; see
  [ADR-0006](0006-drop-on-failure-no-retry-queue.md) for how each handles failure.
</content>
