# bank_learning skill

Teaches HushMoney how to parse notifications from banks that don't have community
patterns yet. Triggered automatically when the sanitizer has no match, or manually
when the user adds a new bank.

## Two modes

**Reactive** (auto-triggered): sanitizer passes the raw message here as a last resort.
This is the only place in the system where Hermes handles pre-sanitization content.
Read `docs/rules/security.md` — the bank_learning exception rules — before touching
anything in this skill.

**Proactive** (user-triggered via `hermes add-bank`): user provides already-redacted
sample messages. No raw content involved.

## What this skill must do

1. Ask the user which bank and country
2. Accept redacted sample messages from the user (proactive) or infer from raw (reactive)
3. Call the NVIDIA model with a **structure-only prompt** — extract field positions,
   delimiters, date formats, strip targets. Never reproduce values.
4. Show inferred transaction summary to user for confirmation
5. On confirmation: store pattern in SQLite under `learned_patterns` table
6. Optionally generate fixture files (`tests/fixtures/{channel}/{bank}/`) for community PR

## Pattern storage schema (SQLite)

```sql
CREATE TABLE learned_patterns (
    id          INTEGER PRIMARY KEY,
    bank_slug   TEXT NOT NULL,        -- e.g. "davivienda"
    country     TEXT NOT NULL,        -- e.g. "CO"
    channel     TEXT NOT NULL,        -- "email" | "sms"
    pattern     TEXT NOT NULL,        -- JSON: field extraction rules
    confirmed   INTEGER DEFAULT 0,    -- 1 = user confirmed at least once
    uses        INTEGER DEFAULT 0,    -- times applied successfully
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
```

## Contributing learned patterns to the community

After 7 days and N successful uses with no corrections, prompt the user:

```
"The Davivienda pattern has been working correctly for 7 days.
 Want me to generate fixture files so others can benefit?
 This creates files in tests/fixtures/ — you can open a PR."
```

If yes: generate `{scenario}.txt` + `{scenario}.expected.json` using synthetic values
(follow `tests/fixtures/SYNTHETIC_DATA.md` rules), write to the repo, notify user.

## What NOT to do

- Do not store raw message content anywhere — not in SQLite, not in logs
- Do not call the model with a prompt that asks it to extract values (amounts, names)
  from the raw message — structural inference only
- Do not apply a learned pattern without user confirmation (reactive mode)
- Do not run in proactive mode with real (non-redacted) samples — if the user pastes
  a real bank message, ask them to redact it first
