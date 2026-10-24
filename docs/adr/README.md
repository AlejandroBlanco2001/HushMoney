# Architecture Decision Records

This directory records the significant architectural decisions in HushMoney, using
the [Nygard format](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions):
each ADR has **Context** (the forces at play), **Decision** (what we chose), and
**Consequences** (what follows, good and bad).

ADRs are immutable once accepted. If a decision changes, write a new ADR that
**supersedes** the old one and update the status of both — don't edit history.

## Status values

- **Proposed** — written, not yet agreed.
- **Accepted** — in force; the code should match it (or an issue tracks the gap).
- **Superseded by ADR-XXXX** — replaced by a later decision.

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [0001](0001-single-user-self-hosted-deployment.md) | Single-user self-hosted deployment | Accepted |
| [0002](0002-privacy-boundary-redact-before-hermes.md) | Privacy boundary: redact before Hermes | Accepted |
| [0003](0003-two-layer-pattern-registry.md) | Two-layer pattern registry (community YAML + learned SQLite) | Accepted |
| [0004](0004-file-based-pattern-inbox.md) | File-based pattern inbox as forwarder↔skill IPC | Accepted |
| [0005](0005-three-transports-into-hermes.md) | Three transports into Hermes | Accepted |
| [0006](0006-drop-on-failure-no-retry-queue.md) | Drop on failure, no retry queue | Accepted |
| [0007](0007-candidate-promotion-policy.md) | Candidate → active promotion policy | Accepted |
| [0008](0008-forwarder-is-stateful.md) | The forwarder is stateful | Accepted |
</content>
</invoke>
