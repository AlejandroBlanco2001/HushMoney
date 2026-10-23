# bank_learning skill

Teaches HushMoney how to parse notifications from banks it hasn't seen before.

## How it is triggered

The forwarder auto-detects financial notifications it cannot parse and forwards them
to Hermes with a `[bank_learning]` header. Only the **redacted** text is forwarded —
no amounts, account numbers, or merchant names. The agent then works with the user
to build a regex pattern, confirms the expected values, and submits a proposal to
the forwarder inbox.

## Security rules

- No raw (unredacted) message content ever appears in this skill.
- The agent must never ask the user to paste unredacted content.
- The agent must never try to reconstruct real values from `[REDACTED]` placeholders.
- Expected values (amount, date) come exclusively from user confirmation — never inferred.
- Proposal files are processed and deleted by the forwarder; they never persist raw text.

## Scripts available

| Script | Purpose |
|--------|---------|
| `get_bank_context.py` | Read current bank registry (templates, separators) |
| `propose_pattern.py` | Submit a validated pattern proposal to the forwarder inbox |
| `mark_ignored.py` | Silence a fingerprint permanently |
| `report_feedback.py` | Send `correct`/`wrong` verdict for a learned pattern |

## Pattern lifecycle

1. **Proposed** → written to `proposals/` directory
2. **Candidate** → validated and accepted; appears in transactions with 🧪 marker
3. **Active** → auto-promoted after 3 distinct uses with no corrections over 24h
4. **Rejected** → bad feedback; fingerprint re-opened for re-learning

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HUSHMONEY_INBOX` | `~/.hermes/pattern-inbox` | Inbox directory for proposals/results |
| `HUSHMONEY_REGISTRY` | `~/.hermes/pattern-inbox/registry.json` | Registry snapshot file |

## What NOT to do

- Do not call older scripts (`query_patterns.py`, `store_pattern.py`) — they are deprecated.
- Do not write directly to the SQLite database — use the inbox scripts.
- Do not submit a proposal without user confirmation of the expected values.
- Do not expose the `[bank_learning]` header content verbatim in your reply.
