# Hermes Agent — HushMoney deployment image
#
# Installs hermes-agent from the official installer, then layers in the
# project's skills and config on top of the base image.
#
# The hermes-agent installer manages Python 3.14, Node.js, and all its own
# deps. We just configure paths and copy our assets.

FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install hermes-agent (manages its own runtime deps)
RUN curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash

# Skills and config are mounted at runtime (see docker-compose.yml / fly.toml).
# The hermes-agent installer sets up /init (s6-overlay PID 1) as the entrypoint.
ENTRYPOINT ["/init", "/opt/hermes/docker/main-wrapper.sh"]
CMD ["gateway", "run"]
