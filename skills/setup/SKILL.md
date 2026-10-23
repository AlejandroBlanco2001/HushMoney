---
name: setup
description: One-time guided onboarding via Telegram
version: 0.4.0
author: hushmoney
metadata:
  hermes:
    tags: [Setup, Onboarding]
    category: hushmoney
    requires_tools: [terminal]
---

# Setup

## When to Use

Triggered by any message from a user whose `setup_complete` setting is not `"true"`.
The user can restart by saying "reset setup" or "resetear".

## Procedure

The wizard manages all state. Your only job is to call it and relay the output.

### Every message during setup

Run:
```
python3 /root/.hermes/skills/hushmoney/setup/scripts/setup_wizard.py --answer "<user message>"
```

Parse the JSON output:
- Send the `message` field verbatim to the user. Do not add to it, summarize it, or ask follow-up questions.
- If `done: true` → setup is complete. Stop running the wizard.

### On first contact (no prior answer)

Run without `--answer` to show the first question:
```
python3 /root/.hermes/skills/hushmoney/setup/scripts/setup_wizard.py
```

### Reset

If the user says "reset setup" or "resetear":
```
python3 /root/.hermes/skills/hushmoney/setup/scripts/save_setting.py wizard_step welcome
python3 /root/.hermes/skills/hushmoney/setup/scripts/save_setting.py setup_complete false
python3 /root/.hermes/skills/hushmoney/setup/scripts/setup_wizard.py
```
Send the output message verbatim.

## Rules

- **Send the `message` field exactly as returned.** Never paraphrase, summarize, or split it.
- **One script call per user message.** Never call the wizard twice in the same turn.
- **Never ask questions yourself.** All questions come from the wizard.
- **Never tell the user to edit files or run commands.** The wizard handles everything internally.

## Pitfalls

- If the wizard outputs `done: true` but `setup_complete` is still `false` in the DB, something
  went wrong — run `mark_setup_complete.py` and tell the user setup is done.
- If the wizard crashes (non-JSON output), reply: "Something went wrong during setup. Try again."
  Then on the next message call the wizard normally with `--answer`.
