# ADR-0003 — Two-layer pattern registry (community YAML + learned SQLite)

- **Status:** Accepted
- **Date:** 2026-10-24

## Context

Bank notifications have to be turned into structured transactions. Banks use dozens of
message formats across countries, and a given user only sees the few from their own
banks. We want known banks to work instantly out of the box, but we also can't ship a
pattern for every bank on earth, and a user hitting an unknown format shouldn't be stuck.

## Decision

Patterns are matched through **two layers plus an LLM fallback**, in order:

1. **Community patterns** — declarative YAML shipped inside the package
   (`sanitizer/patterns/*.yaml`, e.g. `bancolombia.yaml`). Loaded at import by
   `registry.load_community_banks()`. Version-controlled, reviewed, shared via PRs.
2. **Learned patterns** — stored in the user's SQLite DB (`learning/store.py`),
   discovered at runtime and merged on top of community banks by
   `PatternStore.load_active_banks()`. Private to the user's instance.
3. **`bank_learning` skill** — when neither layer matches, the redacted message is
   forwarded to the LLM skill, which infers a candidate pattern and (after user
   confirmation) writes it into layer 2.

Precedence: community and learned patterns for the same bank are concatenated
(`community.transactions + learned`), and `parser.parse` returns the **first** matching
transaction. Learned patterns carry `source='learned'` and a `status` of `candidate`
or `active` (see [ADR-0007](0007-candidate-promotion-policy.md)); community patterns are
always `active`.

The registry snapshots immutably (`RegistrySnapshot`) and reloads from the store at most
every 2s (`REGISTRY_RELOAD_MIN_INTERVAL_S`), keyed off a cheap `data_version()`.

## Consequences

- **Good:** known banks work with zero setup; unknown banks become usable without a code
  change or redeploy. Community knowledge is shareable; learned knowledge stays private.
- **Good:** YAML patterns are reviewable and testable against `tests/fixtures/`. Learned
  patterns go through validation ([ADR-0004](0004-file-based-pattern-inbox.md)) before
  activating.
- **Bad:** a fresh clone ships only one community bank, so most first-time users
  immediately depend on layer 3 (and therefore on a configured LLM). Consider shipping a
  few more example YAMLs.
- **Bad:** learned patterns are compiled with the `regex` module under a timeout
  (`parser._search`), community patterns with stdlib `re`. Two engines, two code paths.
- **Bad:** precedence is positional ("first match wins"), so an over-broad learned
  pattern could shadow a correct community one. Collision checks exist at validation time
  but not at match time.
</content>
