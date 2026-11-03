# Hermes Agent — HushMoney deployment image
#
# Installs hermes-agent from the official installer, then adds a Starlette
# HTTP gateway server so the forwarder can POST messages into the container.
#
# The hermes-agent installer manages its own Python/Node runtimes.
# System python3 + pip are installed separately for the gateway server.

FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    git \
    python3 \
    python3-pip \
    libatomic1 \
    && rm -rf /var/lib/apt/lists/*
# libatomic1: the hermes-agent installer's bundled Node needs it. When the installer
# runs as root it auto-apt-installs missing libs; running it as the 'sandbox' user
# (below) it cannot, so we pre-install it here in the root apt layer.

# OpenShell requires a non-root workload user named 'sandbox' (it rejects root).
# Create it BEFORE the hermes install and run that install AS the user, so the large
# /root/.local dependency tree is owned by 1000:1000 at creation. This avoids a slow
# `chown -R /root` at the end (which would copy the whole tree into a new layer).
# Home is /root so hermes state (/root/.hermes) and the install (/root/.local) are
# found and owned by it. Compose still runs as root (default image user) and can
# read/write these; OpenShell runs as 'sandbox'.
RUN groupadd -g 1000 sandbox \
 && useradd -u 1000 -g 1000 -M -d /root -s /bin/bash sandbox \
 && chown -R sandbox:sandbox /root  # recursive, but /root only holds skeleton dotfiles here
ENV HOME=/root
ENV PATH="/root/.local/bin:$PATH"

# ── Install hermes-agent as 'sandbox' so /root/.local is owned correctly ─────────
USER sandbox

# Install hermes-agent (manages its own runtime deps)
RUN curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash -s -- --skip-computer-use --skip-browser

# Commit the hermes runtime dependency environment at build time. Under OpenShell
# the sandbox network policy blocks PyPI, so a first-run `hermes pm repair` would
# fail there — bake the committed env into the image instead.
RUN hermes pm repair

# Warm up the messaging-platform (telegram) deps at build time too: the gateway
# installs `hermes-agent[telegram]` from PyPI on first run, which the sandbox
# network policy blocks. The warm-up runs the gateway with a dummy token to trigger
# the install, then stops it deterministically — some hermes versions don't exit on
# the rejected token and would otherwise hang the build. See the script for details.
COPY scripts/warmup_telegram_deps.sh /usr/local/bin/warmup_telegram_deps.sh
RUN sh /usr/local/bin/warmup_telegram_deps.sh

# ── Root again for system-level writes (symlink, system pip, app files) ──────────
USER root

# Symlink hermes to /usr/local/bin so OpenShell's sandbox user can execute it
# (OpenShell binds network/filesystem policy rules to the binary path)
RUN ln -sf /root/.local/bin/hermes /usr/local/bin/hermes

# HTTP gateway server + LLM telemetry proxy deps
RUN python3 -m pip install --no-cache-dir --break-system-packages starlette uvicorn httpx

# Bundle skills + config INTO the image. Under docker-compose these are
# bind-mounted (and those mounts still override at runtime), but OpenShell
# sandboxes have no bind mounts — so the image must be self-contained.
COPY skills /opt/data/skills
COPY config/hermes.yaml /opt/data/hermes.yaml
COPY config/hermes.yaml /app/hermes.yaml
COPY config/schema.sql /app/config/schema.sql
COPY config/SOUL.md /app/SOUL.md
COPY config/accounts.md /app/accounts.md
RUN mkdir -p /opt/data/pattern-inbox

COPY gateway_server.py /app/gateway_server.py
COPY llm_proxy.py /app/llm_proxy.py
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

# Only the runtime dirs need chowning now — /root is already sandbox-owned, so this
# stays small and fast (skills + a handful of files), not the whole install tree.
RUN chown -R 1000:1000 /opt/data /app

WORKDIR /app
ENTRYPOINT ["/app/docker-entrypoint.sh"]
