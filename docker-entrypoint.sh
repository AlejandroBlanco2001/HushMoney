#!/bin/sh
set -e

# Source .env if present (uploaded by openshell sandbox create)
if [ -f /app/.env ]; then
    set -a; . /app/.env; set +a
fi

# Write hermes model config — model goes in config.yaml; .env is for secrets only
mkdir -p /root/.hermes
cat > /root/.hermes/config.yaml << 'EOF'
model:
  default: nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B
  provider: openai
  base_url: https://api.studio.nebius.ai/v1/
agent:
  reasoning_effort: low
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
EOF

# Start Telegram gateway in background
hermes gateway run &

# Start HTTP gateway server for the forwarder
exec python3 -m uvicorn gateway_server:app --host 0.0.0.0 --port 8080
