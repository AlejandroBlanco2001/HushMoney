# Git Conventions

## Branch Naming

```
<type>/<short-description>
```

| Type | Use for |
|---|---|
| `feat` | New feature or skill |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `refactor` | Code change with no behavior difference |
| `config` | Changes to `config/` only |
| `chore` | Tooling, dependencies, CI |

Examples: `feat/debt-tracker-skill`, `fix/sanitizer-iban-pattern`, `docs/onboarding-guide`

- Branch off `main`; merge back to `main` via pull request
- Keep branches short-lived — one logical change per branch
- Delete branches after merging

## Commit Messages

```
<type>(<scope>): <short summary in imperative mood>

<optional body — explain WHY, not WHAT>
```

- Summary line: 72 characters max, imperative mood ("add", "fix", "remove" — not "added", "fixes")
- Scope is the component: `forwarder`, `skills`, `config`, `docs`
- Body is optional but useful when the change is non-obvious or has constraints

**Good examples:**
```
feat(skills): add weekly summary rollup to summaries skill

fix(forwarder): strip IBAN patterns from EU bank notifications

docs: add OpenShell policy explanation to architecture.md
```

**Avoid:**
```
fixed stuff
WIP
update
misc changes
```

## Pull Requests

- One PR per logical change — do not bundle unrelated fixes
- PR title follows the same format as a commit message
- PR description must include:
  1. What changed and why
  2. How to test it
  3. Any security implications (especially for `forwarder/` or `config/` changes)
- Do not merge your own PR — at least one other team member reviews it
- All checks (lint, type check, tests) must pass before merging

## What Not to Commit

- `.env` files or any file containing secrets
- `__pycache__/`, `.pyc` files, `.pytest_cache/`
- Editor config files specific to your setup (`.vscode/settings.json`, `.idea/`)
- SQLite database files (`*.db`, `*.sqlite`)
- Any log files

These are covered by `.gitignore`; if you find one slipping through, add it.

## Main Branch

- `main` is always in a deployable state
- Do not force-push to `main`
- Do not commit directly to `main` — always use a branch and PR
