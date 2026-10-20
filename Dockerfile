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
RUN curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash

ENV PATH="/root/.local/bin:$PATH"

# HTTP gateway server deps
RUN python3 -m pip install --no-cache-dir --break-system-packages starlette uvicorn

COPY gateway_server.py /app/gateway_server.py
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

WORKDIR /app
ENTRYPOINT ["/app/docker-entrypoint.sh"]
