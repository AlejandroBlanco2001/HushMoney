# ADR-0001 — Single-user self-hosted deployment

- **Status:** Accepted
- **Date:** 2026-10-24

## Context

HushMoney processes a person's bank notifications — among the most sensitive data a
system can hold. The alternatives are a multi-tenant SaaS (one service, many users'
data) or a single-user deployment (one instance, one person, their own infrastructure).

A SaaS would centralize bank credentials, Telegram tokens, and transaction history for
many people behind one operator. That operator becomes a high-value breach target and a
party the user must trust unconditionally. It also pulls in multi-tenancy concerns —
auth, isolation, per-tenant quotas — that have nothing to do with the actual problem of
parsing a transaction.

## Decision

HushMoney is a **single-user, self-hosted deployment**. One instance runs for one
person on infrastructure they own (e.g. an EC2 t2.micro). The user owns the Telegram bot
token, the email account, the host, and the SQLite database. Nothing is shared with
anyone else, and there is no central service.

Code may assume a single user everywhere: no tenant IDs, no row-level auth, no
per-tenant configuration. Configuration is per-process (environment variables +
`config/hermes.yaml`), not per-tenant.

## Consequences

- **Good:** no central breach target; the trust boundary is the user's own host. No
  multi-tenancy code to build or secure. Data never leaves the user's machine.
- **Good:** simplifies every downstream decision — the DB is local
  ([ADR-0008](0008-forwarder-is-stateful.md)), transports are point-to-point
  ([ADR-0005](0005-three-transports-into-hermes.md)), and "drop on failure" is
  acceptable ([ADR-0006](0006-drop-on-failure-no-retry-queue.md)).
- **Bad:** each user must run and maintain their own instance — higher onboarding cost.
  The open-source path depends on the user bringing their own LLM/host.
- **Bad:** no economies of scale for the community pattern library; sharing learned
  bank formats requires an explicit out-of-band mechanism (PRs to `tests/fixtures/`),
  not a shared backend.
</content>
