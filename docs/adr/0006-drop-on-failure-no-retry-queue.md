# ADR-0006 — Drop on failure, no retry queue

- **Status:** Accepted
- **Date:** 2026-10-24

## Context

Delivery to Hermes can fail: the gateway may be down, the webhook may time out, IMAP may
drop mid-fetch. The classic answer is a durable retry queue with redelivery. The risk
with retries on *financial* notifications is **double-counting**: redelivering the same
transaction records it twice, which is worse than missing it once — a spurious expense is
harder to notice and correct than an absent one.

## Decision

**On delivery failure, drop the message. No retry queue, no redelivery.**

- IMAP marks a message `\Seen` immediately after parsing, *before* dispatch, and
  explicitly does not retry (`imap.py` `_fetch_from_sender`). A dropped message is
  preferred to re-processing.
- Telegram and gateway dispatch failures are logged and swallowed
  (`channels/telegram.py`, `hermes.py`); the update is not re-queued.
- The one place with retry-like behavior is the **learning** path, which is bounded and
  idempotent by design: fingerprints dedupe repeats, a 7-day cooling window
  (`LEARNING_RETRY_AFTER_DAYS`) forwards an unmatched template again, and a rate limit
  (`LEARNING_MAX_PER_HOUR`) caps volume. This is deduplicated re-forwarding of a
  *learning request*, not redelivery of a *transaction*.

This is acceptable because of [ADR-0001](0001-single-user-self-hosted-deployment.md):
one user, low volume, and a human in the loop who sees their own notifications and can
re-enter anything that was missed.

## Consequences

- **Good:** no possibility of double-counting a transaction from redelivery. No durable
  queue to operate, back up, or reason about. Simple failure model.
- **Good:** idempotency is concentrated in the learning path, where fingerprints make it
  safe.
- **Bad:** a transient gateway outage silently loses transactions for its duration. There
  is no dead-letter record, so the user cannot later discover what was dropped beyond log
  lines.
- **Bad:** marking IMAP `\Seen` before a confirmed dispatch means a crash between mark and
  send loses the email with no trace. Accepted deliberately as the lesser evil vs.
  double-counting.
</content>
