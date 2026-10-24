# ADR-0007 — Candidate → active promotion policy

- **Status:** Accepted
- **Date:** 2026-10-24

## Context

A learned pattern starts life as a `candidate` (marked 🧪 in notifications) and should
eventually become `active` once we trust it. The question is **what signal promotes it**.
Two signals are available:

- **Usage** — the pattern successfully parses real notifications over time.
- **Feedback** — the user explicitly confirms a parse was correct (or reports it wrong).

The code today is in a **broken middle state** and must be resolved:

- `docs/architecture.md` and `skills/bank_learning/SKILL.md` promise usage-driven
  promotion: *"auto-promotes to active after 3 distinct successful uses with no
  corrections over 24 hours."*
- `learning/lifecycle.py` implements exactly that in `track_use()` and `_maybe_promote()`
  — but **`track_use()` is never called from anywhere**. `parser.parse` matches a learned
  pattern and never records the use. So `distinct_uses` stays 0 and nothing auto-promotes.
- The only live promotion path is `apply_feedback(verdict='correct')`, driven by the
  `report_feedback` skill. But `apply_feedback(verdict='wrong')` calls
  `row.source_is_community()`, **a method that does not exist** on `LearnedPatternRow`, so
  the "wrong" path raises `AttributeError` at runtime (masked by `# type: ignore`).

Net effect: a user who teaches a bank is stuck with 🧪 candidate markers forever unless
they manually send positive feedback, and negative feedback crashes.

## Decision

Adopt **usage-driven promotion with feedback as an override**, matching the documented
intent:

1. Wire `lifecycle.track_use()` into the learned-pattern success path in `parser.parse`
   (via the sanitize layer, which has the amount/merchant). A candidate promotes to
   `active` after `PROMOTE_AFTER_DISTINCT_USES` distinct uses, zero corrections, and
   `PROMOTE_MIN_AGE_HOURS` age — the thresholds already in `lifecycle.py`.
2. Fix `apply_feedback`: remove the non-existent `source_is_community()` call. Learned
   patterns are never community-sourced, so the guard is dead; drop it. `verdict='wrong'`
   increments corrections, demotes/retires the pattern, and re-opens the fingerprint so
   the next occurrence re-triggers learning. `verdict='correct'` counts as a distinct use.
3. Keep feedback authoritative: one `wrong` outweighs usage and blocks promotion.

The alternative considered — delete `track_use` and make promotion purely feedback-driven
— was rejected: it is simpler but contradicts the existing docs and asks more of the user.

## Consequences

- **Good (if accepted):** learned patterns actually graduate out of 🧪 without nagging the
  user; the documented behavior becomes true; a latent `AttributeError` is removed.
- **Good:** feedback still lets the user correct a bad pattern quickly.
- **Bad:** usage-driven promotion can promote a *wrong* pattern that happens to parse
  consistently (e.g. mislabels a transfer as a payment) if the user never gives feedback.
  The 24h + 3-distinct-use gate mitigates but does not eliminate this.
- **Bad:** wiring `track_use` into the hot parse path adds a DB write per learned-pattern
  match; negligible at single-user volume but worth noting.
</content>
