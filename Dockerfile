# Stage 1: Build standalone virtual environment using uv
FROM ghcr.io/astral-sh/uv:0.6.5-python3.12-bookworm-slim AS builder

WORKDIR /app

# Enable bytecode compilation and independent copy installs
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Copy dependency specifications first to maximize build layer caching
COPY pyproject.toml uv.lock ./

# Install external dependencies into /app/.venv without installing project root
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --no-editable

# Copy source code and install project into virtual environment
COPY README.md LICENSE ./
COPY src/ ./src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# Stage 2: Minimal production runtime container
FROM python:3.12-slim-bookworm AS runtime

LABEL org.opencontainers.image.title="Arthur" \
      org.opencontainers.image.description="Lightweight Headless Chromium Runtime & MCP Server for AI Agents" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.source="https://github.com/sh7vansh/arthur"

# Install Chromium, Tini, and minimal essential fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    tini \
    fonts-liberation \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create non-root system user and group
RUN groupadd -g 10001 arthur && \
    useradd -u 10001 -g arthur -m -d /home/arthur -s /bin/bash arthur

WORKDIR /app

# Copy virtualenv from builder stage
COPY --from=builder --chown=arthur:arthur /app/.venv /app/.venv

# Set runtime environment
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    CHROMIUM_PATH="/usr/bin/chromium" \
    ARTHUR_CONTAINER=1 \
    ARTHUR_NO_SANDBOX=1

# Expose Streamable HTTP FastMCP port
EXPOSE 8000

# Healthcheck probe using Python's built-in socket check (fast, zero dependency)
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python3 -c "import socket; s = socket.create_connection(('127.0.0.1', 8000), timeout=2); s.close()" || exit 1

# Switch to non-root user
USER arthur

# Use tini as PID 1 to reap zombie Chromium subprocesses and manage signals
ENTRYPOINT ["/usr/bin/tini", "--"]

# Default command: Streamable HTTP FastMCP server in stateless mode
CMD ["arthur", "mcp", "--transport", "streamable-http", "--stateless", "--host", "0.0.0.0", "--port", "8000"]
