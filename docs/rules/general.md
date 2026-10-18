# General Coding Rules

Apply these rules to every file in the repository, regardless of language or component.

## Principles

- Write code for the next person to read, not for the machine to execute
- Solve the problem at hand; do not build for hypothetical future requirements
- Three similar lines is better than a premature abstraction
- No half-finished implementations — if a feature is incomplete, leave a `# TODO:` with a specific description, not a vague placeholder

## Code Style

- Functions do one thing; if you need "and" to describe it, split it
- Maximum function length: 50 lines (hard limit in `skills/`; soft limit elsewhere)
- No commented-out code — delete it; Git history is the undo button
- No dead code, unused imports, or unreachable branches
- Boolean parameters in function calls must use keyword form: `send(notify=True)`, not `send(True)`

## Comments

- Default to writing no comments
- Write a comment only when the **why** is non-obvious: a hidden constraint, a workaround for a specific external behavior, a subtle invariant
- Never describe **what** the code does — the code does that
- Never reference the current task, PR, or issue number in a comment

## Error Handling

- Only handle errors you can actually recover from
- Do not catch broad exceptions to silence them — let unexpected errors propagate
- Validate input at system boundaries (HTTP endpoints, file reads, message adapters); trust internal data
- Log errors with enough context to reproduce the problem, but never log the raw message payload from the forwarder (see `security.md`)

## Dependencies

- Do not add a dependency for something that can be implemented in under 20 lines
- Every new dependency must have an upper-bound version pin: `>=x.y,<x+1`
- No transitive dependencies that pull in C extensions unless strictly necessary

## Testing

Not every change needs a test. Write tests for code that is a hard dependency for the system to work correctly — not for every function you touch.

**Write tests when:**
- The code is a trust boundary (the sanitizer, the dispatcher schema, the DB write layer)
- A silent regression would be hard to detect (pattern matching, payload transformation)
- The logic has meaningful branching that each path matters (e.g. cash vs. digital detection)

**Skip tests when:**
- It's a small adjustment (a prompt tweak, a label rename, a config value)
- The behavior is already covered by a broader test above it
- Writing the test would be longer and more brittle than the code itself

**Rules that always apply when you do write tests:**
- Tests verify behavior, not implementation — test what a function does, not how
- No mocking of the SQLite database in integration tests; use a real in-memory SQLite instance
- Test file names mirror source file names: `skills/categorizer/rules.py` → `skills/categorizer/test_rules.py`
- A test that always passes is worse than no test

For LLM-dependent skill logic (categorization accuracy, summary quality), use evals — not unit tests. See `docs/rules/evals.md`.

## Naming

- Names should read as statements: `is_cash_transaction`, `get_weekly_summary`, `sanitize_payload`
- Avoid abbreviations unless they are universally understood (`db`, `url`, `id` are fine; `msg_san_lyr` is not)
- Constants are `UPPER_SNAKE_CASE`; everything else is `lower_snake_case` in Python
