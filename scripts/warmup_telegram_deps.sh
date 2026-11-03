#!/bin/sh
# Build-time warm-up: install the Telegram platform dependencies into the committed
# hermes env so the sandboxed runtime (which has no PyPI access) never needs to fetch
# them at first run.
#
# `hermes gateway run` with a dummy token installs the platform deps and then fails to
# authenticate. Depending on the hermes version it may NOT exit on the rejected token —
# it can sit in a connect/retry loop forever, which previously hung the image build. So
# instead of relying on it to exit, we detect that the dependency install has finished
# (the log stops growing after the install marker, or the process exits) and stop it
# ourselves. A hard deadline guarantees the build can never hang here.
set -u

LOG=/tmp/gw-warmup.log
DEADLINE=$(( $(date +%s) + 300 ))

cat > /root/.hermes/config.yaml <<'YAML'
model:
  default: nvidia/nemotron-3-super-120b-a12b
  provider: openai
platform_toolsets:
  telegram:
    - clarify
    - cronjob
    - file
    - skills
    - terminal
    - todo
YAML

TELEGRAM_BOT_TOKEN=000000:dummy hermes gateway run > "$LOG" 2>&1 &
gw=$!

installed=0
last_size=-1
stable=0
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
    # Gateway exited on its own (older behavior) — install is done.
    if ! kill -0 "$gw" 2>/dev/null; then
        break
    fi
    if grep -q 'Installing Python dependencies' "$LOG" 2>/dev/null; then
        installed=1
    fi
    size=$(wc -c < "$LOG" 2>/dev/null || echo 0)
    # Once deps are installing and the log has been quiet for ~15s, the install has
    # finished and the gateway has moved on to the (doomed) auth step — stop it.
    if [ "$installed" -eq 1 ] && [ "$size" = "$last_size" ]; then
        stable=$((stable + 1))
        if [ "$stable" -ge 5 ]; then
            break
        fi
    else
        stable=0
    fi
    last_size=$size
    sleep 3
done

kill "$gw" 2>/dev/null || true
wait "$gw" 2>/dev/null || true

if grep -q 'Installing Python dependencies' "$LOG" \
    && ! grep -q 'Installing Python dependencies failed' "$LOG"; then
    echo 'telegram deps committed'
else
    echo 'telegram dep warm-up failed to install deps; last log lines:' >&2
    tail -n 40 "$LOG" 2>/dev/null >&2 || true
    exit 1
fi
