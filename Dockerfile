FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN pip install --no-cache-dir hatchling

# Copy project files
COPY pyproject.toml README.md ./
COPY nf_ica_cli/ ./nf_ica_cli/

# Build wheel
RUN pip wheel --no-deps --wheel-dir /app/dist .

# --- Runtime stage ---
FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/UMCCR/nf-ica-cli"
LABEL org.opencontainers.image.description="CLI toolkit for orchestrating Nextflow pipeline deployments to ICA"

# Install system dependencies required at runtime
RUN apt-get update && \
    apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

# Install GitHub CLI
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl gpg && \
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      | gpg --dearmor -o /usr/share/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      > /etc/apt/sources.list.d/github-cli.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends gh && \
    apt-get purge -y curl gpg && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# Install the wheel from builder
COPY --from=builder /app/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl

ENTRYPOINT ["nf-ica"]
