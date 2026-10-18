# Python Rules

Apply these rules when working in `forwarder/` or `skills/`. Read `general.md` first.

## Version and Runtime

- Python 3.12 only — use 3.12 features freely (`type` aliases, improved error messages, `tomllib` in stdlib)
- Use `pyproject.toml` for all package configuration; no `setup.py` or `setup.cfg`
- Virtual environments are managed per-component: `forwarder/` has its own `pyproject.toml`

## Type Hints

- All function signatures must have type hints — parameters and return type
- Use `from __future__ import annotations` at the top of every module for deferred evaluation
- Prefer `X | None` over `Optional[X]`; prefer `X | Y` over `Union[X, Y]`
- Use `TypedDict` for structured dictionaries that cross function boundaries
- Do not use `Any` without a `# noqa: ANN401` comment and a justification

## Async

- Prefer `async`/`await` for I/O-bound code (network calls, file reads in the forwarder)
- Do not mix sync and async code in the same call stack without an explicit bridge
- Never use `asyncio.run()` inside a function — only at the top-level entry point

## Dataclasses and Models

- Use `dataclasses.dataclass(frozen=True)` for value objects (e.g., clean payload, transaction record)
- Do not use mutable default arguments — use `field(default_factory=...)`
- `pydantic` is acceptable for HTTP boundary validation; do not use it for internal data structures

## Imports

- Standard library → third-party → local, separated by blank lines
- No wildcard imports (`from x import *`)
- Absolute imports only — no relative imports

## Logging

- Use the stdlib `logging` module; do not use `print()` for anything other than CLI output
- Logger names follow the module path: `logging.getLogger(__name__)`
- Log levels: `DEBUG` for trace-level flow, `INFO` for significant state changes, `WARNING` for recoverable anomalies, `ERROR` for failures
- Never log raw message payloads — see `security.md`

## File Structure (per component)

```
component/
├── pyproject.toml
├── src/
│   └── component_name/
│       ├── __init__.py
│       └── ...
└── tests/
    └── ...
```

## Tooling

- Formatter: `ruff format` (replaces Black)
- Linter: `ruff check`
- Type checker: `pyright` in strict mode
- Tests: `pytest`; run via `scripts/run_tests.sh` from repo root — never bare `pytest`
- All four must pass before a PR is opened

## What to Test in the Forwarder

The forwarder has one job that must never silently fail: stripping sensitive data before dispatch. Focus test coverage on that boundary.

| Module | Test? | Why |
|---|---|---|
| `sanitizer/` | **Yes — always** | Privacy boundary; a miss leaks PII to Hermes |
| `dispatcher/` | **Yes** | Schema mismatch silently corrupts Hermes input |
| `channels/email.py` | Light integration test with a recorded payload | Adapter logic, not complex |
| `channels/telegram.py` | Light integration test with a recorded update | Same |
| `/confirm` endpoint | **Yes** | Used during setup to relay Gmail confirmation code; must be reliable |

Use `hypothesis` for sanitizer fuzz testing — generate arbitrary strings and assert no sensitive patterns survive. A regex that passes all hand-written examples but fails on a real bank message format is a real risk.
