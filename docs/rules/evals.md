# Evals — Hermes Skills Testing Strategy

Read this when working in `skills/`. Unit tests alone are not enough for LLM-dependent code, but evals are also not required for every skill change. This file explains what gets what.

## The Core Split

| Code type | What to use | When to write it |
|---|---|---|
| Deterministic skill logic — SQLite reads/writes, payload parsing, field mapping | `pytest` unit test | Whenever you add or change this logic |
| LLM-dependent output — categorization, summary text, question phrasing | Eval (golden dataset or LLM-as-judge) | When you add a new skill or change a prompt that affects output quality |
| Small adjustments — prompt wording tweak, label rename, config value change | Nothing | These don't need coverage |
| Skill execution order / tool call sequence | `pytest` assertion on Hermes trace | When the sequence matters for correctness |

The goal is coverage of things that break silently and hurt the user. A wrong category on one transaction is acceptable. A sanitizer that lets an OTP through, or a categorizer that reliably misclassifies groceries as dining, is not.

## Eval Types

### 1. Golden Dataset (categorizer, expense_tracker)

A curated JSONL file of clean payloads with known correct outputs. The eval script runs each payload through the skill and measures accuracy.

```
skills/categorizer/evals/
├── golden.jsonl          # { "input": <clean payload>, "expected_category": "dining" }
└── run_evals.py          # loads golden.jsonl, calls the skill, reports accuracy
```

**Threshold:** set a minimum accuracy (e.g. 85%) that the eval must meet for CI to pass. If a prompt change drops accuracy below threshold, it must be justified or fixed before merging.

Golden dataset entries are added whenever the agent miscategorizes a real transaction — it becomes a regression test.

### 2. LLM-as-Judge (summaries)

Summary quality is subjective, so a second model call scores it. The judge prompt checks:
- Does the summary correctly reflect the transaction set?
- Are the totals accurate?
- Is the tone appropriate (not alarming, not dismissive)?

```
skills/summaries/evals/
├── fixtures/             # sample transaction sets with known totals
└── judge.py             # calls model, scores output 1–5, fails below threshold
```

Run these locally before changing summary prompts. They are not in CI by default (they cost real inference tokens).

### 3. Trajectory Assertions (setup, multi-step skills)

For skills that call other skills or tools in a specific order, assert the sequence in a unit test using Hermes's execution trace. No LLM call needed — just verify the agent chose the right steps.

```python
# Example: setup skill must call playwright before confirming
trace = run_skill("setup", payload=...)
assert trace.calls[0].tool == "playwright_navigate"
assert trace.calls[-1].tool == "telegram_send"
```

## What Explicitly Does NOT Need Coverage

- Prompt wording changes that don't alter structured output (tone, phrasing improvements)
- Adding a new spending category label to a lookup table
- Config value changes in `hermes.yaml`
- Changes to summary schedule timing
- Cosmetic changes to Telegram message formatting

If you're unsure, ask: "if this silently regresses, would the user notice something wrong with their data?" If no — skip the test.

## Running Evals

```bash
# Deterministic tests only (fast, no model calls)
scripts/run_tests.sh

# Categorizer golden dataset eval (requires NEBIUS_API_KEY)
python skills/categorizer/evals/run_evals.py

# Summary judge eval (costs tokens — run before significant prompt changes)
python skills/summaries/evals/judge.py
```

## Adding to the Golden Dataset

When Hermes miscategorizes a real transaction:
1. Record the clean payload and the correct category
2. Add it to `skills/categorizer/evals/golden.jsonl`
3. Run the eval to confirm the new entry fails before your fix, passes after

This turns every real-world mistake into a regression test.
