# ADR-0008 — The forwarder is stateful

- **Status:** Accepted
- **Date:** 2026-10-24
- **Supersedes:** the "stateless, no database, no retry queue" claim in
  `docs/architecture.md`

## Context

The forwarder was originally designed as a pure pipe: two channels in (IMAP, Telegram),
one channel out (Hermes), holding no state. `docs/architecture.md` still says *"The
forwarder holds no state, no database, no retry queue."*

The runtime learning subsystem ([ADR-0003](0003-two-layer-pattern-registry.md),
[ADR-0004](0004-file-based-pattern-inbox.md)) changed this. The forwarder now owns:

- a **SQLite database** (`learning/store.py`, `PatternStore`) holding learned banks,
  learned patterns, fingerprints, and a proposal log;
- a **file-based inbox** (`pattern-inbox/`) with `proposals/`, `processing/`, `results/`;
- in-memory caches (the `RegistrySnapshot`) and a process-global rate-limit list.

The "stateless" description is now simply false, and it misleads anyone reading the doc
before the code.

## Decision

Acknowledge that **the forwarder is stateful**, and treat that state as a first-class part
of its design:

- The SQLite DB at `FORWARDER_DB_PATH` is durable, per-user state that must survive
  restarts and be included in any backup story.
- The `pattern-inbox/` directory is durable IPC state with crash recovery
  (`_recover_processing`).
- `docs/architecture.md` must be corrected to describe the forwarder as holding a learned
  pattern store and inbox, not as stateless.

The *transaction* path remains effectively stateless and drop-on-failure
([ADR-0006](0006-drop-on-failure-no-retry-queue.md)) — no transaction is persisted in the
forwarder. The new state is entirely about **learning**, not about buffering
transactions.

## Consequences

- **Good:** the doc matches reality; new contributors understand there is a DB to back up
  and an inbox to reason about.
- **Good:** keeps a clean mental split — transactions flow through statelessly; only
  learned knowledge is persisted.
- **Bad:** operations now include a DB file and inbox directory (backup, disk, WAL
  files). The single-user assumption ([ADR-0001](0001-single-user-self-hosted-deployment.md))
  keeps this light, but it is no longer "just a pipe."
- **Bad:** some state is still in the wrong place — e.g. the hourly learning rate limit
  lives in a module-global list (`learning/unmatched.py`) rather than the store, so it is
  lost on restart and not shared across the sync/async paths. A follow-up should move it
  into `PatternStore`.
</content>
