# ADR-0004 — File-based pattern inbox as forwarder↔skill IPC

- **Status:** Accepted
- **Date:** 2026-10-24

## Context

When the `bank_learning` skill infers a new pattern, that proposal has to reach the
forwarder, be validated (regex safety, reproduces the confirmed amount/date, doesn't
collide with an existing template), and — if accepted — be written into the learned
pattern store. The skill runs as scripts inside the Hermes **OpenShell sandbox**; the
forwarder runs as a separate process. They need an IPC channel across that boundary.

Options considered: an HTTP endpoint on the forwarder, a shared SQLite table the skill
writes directly, or a shared directory of files.

## Decision

Use a **file-based inbox** (`learning/inbox.py`, `InboxWatcher`). The skill's
`propose_pattern.py` writes a JSON proposal into `pattern-inbox/proposals/`; the
forwarder polls that directory (1s), moves each file to `processing/`, validates it,
applies accepted patterns to the store, and writes an outcome to `pattern-inbox/results/`
which the skill reads back. Writes use temp-file + atomic `rename`. A `registry.json`
snapshot is written for the skill to read current bank/template context.

Rationale for files over HTTP or a shared DB:

- The sandbox's filesystem policy already governs which directories the skill can touch;
  a shared directory is the natural, auditable seam. No new listening port, no secret to
  share between skill and forwarder.
- The forwarder, not the skill, owns the pattern store and all validation. The skill can
  only *propose*; it can never write a pattern directly. A shared DB table would let the
  skill bypass validation.
- Crash-safety is trivial: files in `processing/` are recovered back to `proposals/` on
  startup (`_recover_processing`).

## Consequences

- **Good:** strong privilege separation — all validation and writes are forwarder-side.
  Durable and crash-recoverable by construction. No extra network surface.
- **Good:** the request/response contract is inspectable on disk, which makes the skill
  easy to test and debug.
- **Bad:** ~1s polling latency and a busy-wait thread. Fine for interactive learning,
  not for high throughput.
- **Bad:** two moving directories and a recovery path to reason about; `results/` files
  accumulate unless cleaned. Correctness depends on atomic-rename semantics of the
  underlying filesystem.
</content>
