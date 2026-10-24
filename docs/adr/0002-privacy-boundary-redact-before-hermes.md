# ADR-0002 — Privacy boundary: redact before Hermes

- **Status:** Accepted
- **Date:** 2026-10-24

## Context

The forwarder receives raw bank notifications containing OTPs, account numbers, Bre-B
keys (which are indistinguishable from national ID numbers or phone numbers), and
personal names. The Hermes agent runs an LLM; anything Hermes sees may be sent to a
model provider (Nebius), logged, or written to the agent's store. We need a clear rule
about what the LLM is ever allowed to see.

## Decision

**All raw notification text is redacted before it reaches Hermes.** Redaction happens in
the forwarder (`sanitizer/redaction.py`) and runs on every path — the deterministic
sanitizer redacts before parsing, and the learning path redacts before building the
`[bank_learning]` envelope. Downstream components (`gateway_server.py`, skills) only ever
see already-redacted text and structured `CleanPayload` fields.

**One documented exception — reactive bank learning.** When neither pattern layer matches
(see [ADR-0003](0003-two-layer-pattern-registry.md)), the redacted text is forwarded to
the `bank_learning` skill so the LLM can infer *structure*. Constraints that MUST hold:

- The text forwarded is the **already-redacted** text — amounts/accounts show as
  `[REDACTED]`. The skill is instructed never to ask for raw values and never to
  reproduce the redacted text verbatim (`skills/bank_learning/SKILL.md`).
- The LLM infers structure only (field positions, delimiters, formats), not values.
- A `fingerprint` (not the content) is the deduplication key.
- Lines that could spoof the `[bank_learning]` envelope header are stripped before
  forwarding (`learning/unmatched.py`).

> **Note on the architecture prose:** `docs/architecture.md` describes a stronger
> exception where Hermes briefly sees *pre-sanitization* content. The code does **not**
> do that — it forwards redacted text only. This ADR reflects the code. The prose should
> be corrected to match.

## Consequences

- **Good:** the LLM provider never receives OTPs, account numbers, or amounts. The
  privacy boundary is one function (`redact`) on one side of the process.
- **Good:** the learning exception is narrow and auditable — redacted text + a hash.
- **Bad:** redaction is regex-based and conservative; it can over-redact (e.g. a 6+ digit
  merchant code) or, if a new bank uses an unusual format, under-redact. The rules in
  `redaction.py` are the trusted core and need review whenever a new locale is added.
- **Bad:** because learning only sees redacted text, the skill cannot auto-derive actual
  amounts; it must ask the user to confirm values before a pattern is validated.
</content>
