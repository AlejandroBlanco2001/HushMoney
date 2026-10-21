#!/bin/sh
set -e

# Source .env if present (uploaded by openshell sandbox create)
if [ -f /app/.env ]; then
    set -a; . /app/.env; set +a
fi

mkdir -p /root/.hermes

# Install hushmoney skills into hermes skills directory (full copy including scripts)
for skill in expense_tracker setup categorizer summaries debt_tracker bank_learning; do
    mkdir -p "/root/.hermes/skills/hushmoney/$skill"
    cp -r "/opt/data/skills/$skill/." "/root/.hermes/skills/hushmoney/$skill/"
done

# Check current setup state
SETUP_STATE=$(python3 /opt/data/skills/setup/scripts/seed_defaults.py 2>/dev/null \
    || echo '{"setup_complete":"false","setup_step":"start"}')
SETUP_COMPLETE=$(echo "$SETUP_STATE" | python3 -c \
    "import json,sys; print(json.load(sys.stdin).get('setup_complete','false'))" 2>/dev/null \
    || echo "false")
SETUP_STEP=$(echo "$SETUP_STATE" | python3 -c \
    "import json,sys; print(json.load(sys.stdin).get('setup_step','start'))" 2>/dev/null \
    || echo "start")

# Build system_prompt based on setup state.
# agent.system_prompt in config.yaml is loaded at gateway startup (confirmed in hermes
# gateway/run.py:3273) — the only injection point that survives the SOUL.md gateway bug
# (NousResearch/hermes-agent#26596).
if [ "$SETUP_COMPLETE" = "false" ]; then
    SYSTEM_PROMPT="You are HushMoney, a personal finance assistant.

CRITICAL: setup_complete is FALSE. The user has not finished onboarding.
You MUST invoke the hushmoney/setup skill as your very first action for ANY message.
Do not greet, answer questions, or do anything else until setup is complete.
Use the skills tool to invoke: hushmoney/setup"
else
    SYSTEM_PROMPT="You are HushMoney, a personal finance assistant. Setup is complete.
Help the user track expenses, summarize spending, and manage debts.

Routing:
- Transaction JSON (amount+currency+bank) → hushmoney/expense_tracker skill
- Spending questions → hushmoney/summaries skill
- Debt/split questions → hushmoney/debt_tracker skill
- /reset-setup → run save_setting.py setup_complete false, then hushmoney/setup skill"
fi

# Write hermes config — system_prompt is loaded at gateway startup (run.py:3273)
cat > /root/.hermes/config.yaml << CONFEOF
model:
  default: nvidia/nemotron-3-super-120b-a12b
  provider: openai
  base_url: https://api.studio.nebius.ai/v1/
agent:
  reasoning_effort: low
  system_prompt: |
$(echo "$SYSTEM_PROMPT" | sed 's/^/    /')
platform_toolsets:
  telegram:
    - clarify
    - cronjob
    - file
    - skills
    - terminal
    - todo
  cli:
    - clarify
    - cronjob
    - file
    - skills
    - terminal
    - todo
CONFEOF

# SOUL.md — identity/tone (may be ignored in gateway due to bug #26596, but set anyway)
cat > /root/.hermes/SOUL.md << 'EOF'
# Identity
You are HushMoney, a personal finance assistant. You help users track expenses,
split debts, and understand where their money goes.

# Style
Short, friendly, practical. Match the user's language (Spanish or English).
No filler phrases. No restating the question.
EOF

# AGENTS.md — routing rules (context tier, loaded from ~/.hermes per prompt_builder.py:1469)
cat > /root/.hermes/AGENTS.md << AGEOF
# HushMoney rules

setup_complete = ${SETUP_COMPLETE}
setup_step = ${SETUP_STEP}

Skills path: /opt/data/skills/<skill>/scripts/
DB: ~/.hermes/hushmoney.db
Schema fix: python3 -c "import sqlite3; con=sqlite3.connect('/root/.hermes/hushmoney.db'); con.executescript(open('/app/config/schema.sql').read()); con.close()"
AGEOF

# Start Telegram gateway in background
hermes gateway run &

# Start HTTP gateway server for the forwarder
exec python3 -m uvicorn gateway_server:app --host 0.0.0.0 --port 8080
