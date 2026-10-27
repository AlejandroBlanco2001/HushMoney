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
    && rm -rf /var/lib/apt/lists/*

# Install hermes-agent (manages its own runtime deps)
RUN curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash -s -- --skip-computer-use --skip-browser

ENV PATH="/root/.local/bin:$PATH"

# Symlink hermes to /usr/local/bin so OpenShell's sandbox user can execute it
# (OpenShell binds network/filesystem policy rules to the binary path)
RUN ln -sf /root/.local/bin/hermes /usr/local/bin/hermes

# Commit the hermes runtime dependency environment at build time. Under OpenShell
# the sandbox network policy blocks PyPI, so a first-run `hermes pm repair` would
# fail there — bake the committed env into the image instead.
RUN hermes pm repair

# HTTP gateway server deps
RUN python3 -m pip install --no-cache-dir --break-system-packages starlette uvicorn

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
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

# OpenShell requires a non-root workload user named 'sandbox' (it rejects root).
# Give it /root as its home so the hermes state the entrypoint writes
# (/root/.hermes) and the hermes install (/root/.local) are owned and found by it,
# then hand it the runtime dirs. Compose still runs as root and can write these.
RUN groupadd -g 1000 sandbox \
 && useradd -u 1000 -g 1000 -M -d /root -s /bin/bash sandbox \
 && chown -R 1000:1000 /root /opt/data /app

WORKDIR /app
ENTRYPOINT ["/app/docker-entrypoint.sh"]
