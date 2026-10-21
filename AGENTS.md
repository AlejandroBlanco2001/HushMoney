# HushMoney — AI Assistant Guide

This is the primary entry point for any AI coding assistant (Claude, Cursor, OpenCode, Copilot, etc.) working in this repository. Read this file first, then follow the links to area-specific rules.

## What Is HushMoney?

HushMoney is a zero-input expense tracker. It intercepts bank email notifications by polling Gmail via IMAP, routes the parsed message to **Hermes Agent** — an AI agent that categorizes expenses, tracks debts, and delivers summaries — and delivers results via Telegram.

Users never manually enter a transaction. The system does it for them.

## Repository Layout

```
hushmoney/
├── AGENTS.md                  ← you are here
├── config/
│   ├── hermes.yaml            ← Hermes runtime config (no secrets)
│   └── schema.sql             ← SQLite schema applied by Hermes on first run
├── docker-compose.yml         ← local + EC2 orchestration
├── docker-entrypoint.sh       ← starts hermes gateway run + uvicorn
├── Dockerfile                 ← Hermes container image with gateway server
├── docs/
│   ├── architecture.md        ← data flow, component map, integration points
│   ├── deployment.md          ← EC2 + Docker setup for the team
│   ├── onboarding.md          ← guide for non-developers using Cursor/OpenCode
│   └── rules/
│       ├── general.md         ← language-agnostic conventions (read for every task)
│       ├── python.md          ← Python 3.12 specifics (read when touching forwarder/)
│       ├── security.md        ← PII/OTP rules (read when touching forwarder/ or config/)
│       ├── evals.md           ← eval strategy for Hermes skills (read when touching skills/)
│       └── git.md             ← branch and commit conventions
├── evals/
│   └── model_selection/       ← model eval experiments (see evals.md)
├── forwarder/                 ← Python 3.12 — polls Gmail, parses emails, dispatches to Hermes
│   ├── src/forwarder/
│   │   ├── channels/
│   │   │   ├── telegram.py        ← Starlette webhook server for SMS relay via Telegram
│   │   │   └── telegram_config.py ← config loader for Telegram channel
│   │   ├── sanitizer/
│   │   │   ├── banks.py           ← Bancolombia (and future banks) regex patterns
│   │   │   ├── models.py          ← CleanPayload, Channel, TransactionType types
│   │   │   ├── parser.py          ← applies bank pattern to extract structured fields
│   │   │   ├── redaction.py       ← strips OTPs, account numbers, card numbers
│   │   │   └── selector.py        ← matches raw text to a known bank
│   │   ├── __main__.py            ← poll loop entry point
│   │   ├── config.py              ← env var loading
│   │   ├── hermes.py              ← HTTP POST CleanPayload to gateway_server
│   │   └── imap.py                ← IMAP polling + RFC 822 parsing
│   └── tests/
│       ├── test_bank_selection.py
│       ├── test_config.py
│       ├── test_hermes.py
│       ├── test_imap.py
│       ├── test_main.py
│       ├── test_redaction.py
│       ├── test_sanitizer.py
│       ├── test_telegram.py
│       └── test_telegram_config.py
├── gateway_server.py          ← Starlette HTTP server inside the Hermes container
├── scripts/
│   └── setup.sh               ← one-shot EC2 bootstrap + deploy
├── skills/                    ← custom Hermes skills loaded by the agent at runtime
│   ├── setup/                 ← one-time guided setup via Telegram (runs once)
│   ├── bank_learning/         ← learns new bank formats from user samples
│   ├── expense_tracker/
│   ├── categorizer/
│   ├── debt_tracker/
│   └── summaries/
└── tests/
    └── fixtures/
        └── emails/bancolombia/ ← real email samples (.eml) used in tests
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
| Agent sandbox | NVIDIA OpenShell (planned) |
| Models | NVIDIA open models via Nebius Serverless |
| Infra | AWS EC2 t2.micro (free tier) |
| Email ingestion | Gmail IMAP polling (App Password) |
| HTTP gateway | Starlette + uvicorn (`gateway_server.py`) |
| Forwarder | Python 3.12 |
| Database | SQLite (managed by Hermes) |
| User notifications | Telegram |

## Product Direction

HushMoney is competing in the **NVIDIA Personal AI Track** (`docs/path.md`). The judging criteria shape every product decision. When in doubt about what to build next, use this section as the compass.

### North Star

An always-on, private financial assistant that runs on infrastructure you own, processes your data locally, and requires zero manual input from the user.

### What "Done" Looks Like for the Hackathon

| Criterion | Current state | Gap |
|---|---|---|
| Always-on | Forwarder polls IMAP; Pyrogram listener watches Telegram | OpenShell gateway unstable on NixOS |
| Private / data under control | All data in local SQLite; sanitizer strips PII before Hermes sees it | Good — maintain this |
| Persistent memory | SQLite via Hermes skills | Expand: spending patterns, user preferences, debt history |
| Reusable skills | expense_tracker, categorizer, debt_tracker, summaries, bank_learning | Add: budget alerts, recurring detection, multi-bank |
| NVIDIA open model | Nebius Serverless wired | Confirm model is NVIDIA open-weight (e.g. Llama or Mistral on Nebius) |
| OpenShell sandbox | Planned — blocked by NixOS kernel restriction (`/dev/kmsg`) | Fix or demo on a Linux VM where rootless k3s works |
| Hermes Agent | Core runtime | Skills are the extension point — keep the core narrow |
| Nebius Serverless | Inference provider registered | Already done |

### Where to Add Capability

New user-facing features belong in `skills/` — not in the forwarder, not in `gateway_server.py`. The forwarder's job is to deliver a clean, structured `CleanPayload`; Hermes decides what to do with it.

New ingestion sources (SMS, push notifications, other banks) belong in `forwarder/` as new channel modules alongside `imap.py`.

### What Not to Build

- Do not add retry logic, queuing, or state to the forwarder — it must stay stateless.
- Do not put secrets or user preferences in `config/hermes.yaml` — only non-secret behavior config goes there.
- Do not duplicate parsing logic between channels — the sanitizer in `forwarder/sanitizer/` is shared by all of them.

## Core Invariants

These must not be violated under any circumstances:

1. **No raw financial data leaves the forwarder unsanitized.** The sanitizer is the trust boundary — everything downstream receives `CleanPayload` only.
2. **No PII, OTPs, or account numbers are ever logged.** See `docs/rules/security.md`.
3. **Skills live at the edge.** New capabilities go into `skills/`, not into Hermes core. This mirrors Hermes's own architecture principle: keep the core narrow.
4. **Hermes config is the source of truth for behavior.** Do not use environment variables for non-secret configuration; put it in `config/hermes.yaml`.
5. **The forwarder is stateless.** It polls, parses, and dispatches. It does not store, retry-queue, or make decisions about transactions.

## Routing Table

- Forwarder internals → `docs/rules/python.md` + `docs/rules/security.md`
- Skills development → `docs/rules/python.md` + `docs/rules/evals.md`
- Hermes configuration → `config/` + `docs/architecture.md`
- Onboarding a new team member → `docs/onboarding.md`
