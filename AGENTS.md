# HushMoney — AI Assistant Guide

This is the primary entry point for any AI coding assistant (Claude, Cursor, OpenCode, Copilot, etc.) working in this repository. Read this file first, then follow the links to area-specific rules.

## What Is HushMoney?

HushMoney is a zero-input expense tracker. It intercepts financial notifications (bank emails, SMS alerts, messaging apps), strips all sensitive information, and routes clean transaction signals to **Hermes Agent** — a self-improving AI agent that categorizes expenses, tracks debts, and delivers summaries.

Users never manually enter a transaction. The system does it for them.

## Repository Layout

```
hushmoney/
├── AGENTS.md                  ← you are here
├── README.md
├── docs/
│   ├── architecture.md        ← data flow, component map, integration points
│   ├── onboarding.md          ← guide for non-developers using Cursor/OpenCode
│   └── rules/
│       ├── general.md         ← language-agnostic conventions (read for every task)
│       ├── python.md          ← Python 3.12 specifics (read when touching forwarder/)
│       ├── security.md        ← PII/OTP rules (read when touching forwarder/ or config/)
│       ├── evals.md           ← eval strategy for Hermes skills (read when touching skills/)
│       └── git.md             ← branch and commit conventions
├── forwarder/                 ← Python 3.12 — receives, sanitizes, dispatches messages
│   └── src/
│       ├── channels/
│       │   ├── email.py       ← HTTP POST from Cloudflare Email Worker
│       │   └── telegram.py    ← Telegram Bot API (user's own bot)
│       ├── sanitizer/         ← strip OTP, account numbers, PII
│       ├── dispatcher/        ← POST clean payload to Hermes
│       └── confirm.py         ← /confirm endpoint: relays Gmail setup code back to Hermes
├── skills/                    ← custom Hermes skills loaded by the agent at runtime
│   ├── setup/                 ← one-time guided setup via Telegram (runs once)
│   ├── expense_tracker/
│   ├── categorizer/
│   ├── debt_tracker/
│   └── summaries/
└── config/                    ← Hermes config, OpenShell policy, system prompts
    ├── hermes.yaml
    ├── cloudflare/            ← Email Worker script + wrangler config
    ├── openshell/
    └── prompts/
```

## Rule Files — Read Before Touching an Area

| Area | Rules to load |
|---|---|
| Any file in the repo | `docs/rules/general.md` + `docs/rules/git.md` |
| `forwarder/` | + `docs/rules/python.md` + `docs/rules/security.md` |
| `skills/` | + `docs/rules/python.md` + `docs/rules/evals.md` |
| `config/` | + `docs/rules/security.md` |

## Tech Stack at a Glance

| Component | Technology |
|---|---|
| Agent runtime | [Hermes Agent](https://github.com/NousResearch/hermes-agent) (NousResearch) |
| Agent sandbox | NVIDIA OpenShell |
| Models | NVIDIA open models via Nebius |
| Infra | Nebius AI Cloud |
| Forwarder | Python 3.12 |
| Database | SQLite (managed by Hermes) |
| User notifications | Telegram (cash operations only) |

## Core Invariants

These must not be violated under any circumstances:

1. **No raw financial data leaves the forwarder unsanitized.** The sanitizer is the trust boundary. Everything downstream of it handles clean, non-sensitive payloads only.
2. **No PII, OTPs, or account numbers are ever logged.** See `docs/rules/security.md`.
3. **Skills live at the edge.** New capabilities go into `skills/`, not into Hermes core. This mirrors Hermes's own architecture principle: keep the core narrow.
4. **Hermes config is the source of truth for behavior.** Do not use environment variables for non-secret configuration; put it in `config/hermes.yaml`.
5. **The forwarder is stateless.** It receives, sanitizes, and dispatches. It does not store, retry-queue, or make decisions about transactions.
6. **Two channels in, one channel out.** The forwarder's only input channels are Cloudflare Email Workers (email) and Telegram Bot API (SMS relay + messaging). No IMAP, no Twilio, no OAuth flows.

## Routing Table

- Forwarder internals → area `AGENTS.md` will live at `forwarder/AGENTS.md` (not yet written — start from `docs/rules/python.md` + `docs/rules/security.md`)
- Skills development → area `AGENTS.md` will live at `skills/AGENTS.md` (not yet written — start from `docs/rules/python.md`)
- Hermes configuration → `config/` + `docs/architecture.md`
- Onboarding a new team member → `docs/onboarding.md`
