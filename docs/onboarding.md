# Onboarding Guide — Non-Developer Workflow

This guide is for team members who will use an AI coding assistant (Cursor, OpenCode, or Claude) to contribute to HushMoney without writing code from scratch.

## What You Need Installed

- [Cursor](https://cursor.sh) or [OpenCode](https://opencode.ai) — your AI-powered editor
- [Git](https://git-scm.com/downloads) — to save and share your changes
- Python 3.12 — only needed if you want to run the forwarder locally

You do not need to know how to code. The AI assistant will write the code; your job is to describe what you want clearly and review what it produces.

## How This Repo Is Organized

Before asking the AI to do anything, tell it to read `AGENTS.md`. That file explains the whole project to the AI so it understands the rules before touching anything.

In Cursor you can do this by opening a chat and typing:
```
Read AGENTS.md and tell me what you understand about this project before we start.
```

## Making a Change: Step by Step

### 1. Understand what you want to change

Be specific. Instead of "improve the categorizer", say:
> "The categorizer should recognize 'Netflix' and 'Spotify' as Entertainment, not Subscriptions."

### 2. Tell the AI which area you're working in

The AI needs to know which rule files to follow. Tell it upfront:
> "We're working in `skills/categorizer/`. Read AGENTS.md and `docs/rules/general.md` before starting."

### 3. Ask for a plan first

Before the AI writes any code, ask it to explain what it's going to do:
> "Don't write any code yet — tell me your plan first."

Review the plan. If something looks wrong or surprising, push back before it starts.

### 4. Review the changes

After the AI makes changes, ask it to summarize what it changed and why. Then look at the actual files — you don't need to understand every line, but you should be able to read it at a high level.

### 5. Save your work with Git

Once you're happy with the change, commit it:
```
git add .
git commit -m "short description of what changed"
```

Or ask the AI to do it for you:
> "Commit these changes with a clear message."

## Rules the AI Must Follow

These are not optional. If the AI suggests something that breaks one of these rules, tell it to stop and find a different approach.

| Rule | Why it matters |
|---|---|
| No PII, OTPs, or account numbers in logs | User financial data must stay private |
| Forwarder is stateless | It must not store anything; it only passes messages through |
| New features go in `skills/`, not Hermes core | Keeps the agent clean and upgradable |
| Config goes in `config/hermes.yaml`, not env vars | Keeps behavior visible and version-controlled |
| No new dependencies without discussion | Adds maintenance burden and security surface |

## Asking Good Questions

The AI works best when you give it context. Compare:

**Vague:**
> "Fix the summaries."

**Good:**
> "The weekly summary in `skills/summaries/` is not including transactions from Saturday. I want it to cover Monday through Sunday. Read AGENTS.md and `docs/rules/python.md` first."

## When Something Goes Wrong

- If the AI writes code that breaks things, ask: `"Revert the last change and explain what went wrong."`
- If you're not sure whether a change is safe, ask: `"Does this change affect any sensitive data handling? Check against docs/rules/security.md."`
- If you get stuck, check `docs/architecture.md` — it has a diagram of how everything connects.

## Glossary

| Term | Meaning |
|---|---|
| **Hermes** | The AI agent at the core of HushMoney — it remembers transactions and generates summaries |
| **Forwarder** | The service that receives your bank's messages and removes sensitive information before passing them to Hermes |
| **Skill** | A specific capability Hermes has — like categorizing an expense or generating a weekly summary |
| **SQLite** | A lightweight database where Hermes stores all your transaction history |
| **Gateway** | The HTTP server inside the Hermes container that receives emails from the forwarder and passes them to Telegram |
