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
    git \
    && rm -rf /var/lib/apt/lists/*

# Install hermes-agent (manages its own runtime deps)
RUN curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash

ENV PATH="/root/.local/bin:$PATH"

ENTRYPOINT ["hermes"]
CMD ["gateway", "run"]
