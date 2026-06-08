# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2025-2026 ViralMint Contributors
#
# Dockerfile for Hugging Face Spaces deployment.
# Build:   docker build -t viralmint .
# Run:     docker run -p 7860:7860 -e HOST=0.0.0.0 viralmint
#
# HF Spaces automatically sets PORT=7860 and expects the app
# to bind to 0.0.0.0.

FROM python:3.11-slim AS builder

# Prevent apt from prompting
ENV DEBIAN_FRONTEND=noninteractive

# Install system deps needed for building Python native extensions
# (cryptography, faster-whisper, etc.) and for Node.js.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    gnupg \
    gcc \
    g++ \
    make \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 20.x (LTS) via NodeSource
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && npm --version && node --version

# ── Final stage ───────────────────────────────────────────────────────
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV HOST=0.0.0.0

# Install runtime system dependencies:
#   ffmpeg, imagemagick — required by ViralMint
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    imagemagick \
    curl \
    ca-certificates \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Copy Node.js from builder stage
COPY --from=builder /usr/local/bin/node /usr/local/bin/node
COPY --from=builder /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=builder /usr/local/bin/npm /usr/local/bin/npm
COPY --from=builder /usr/local/bin/npx /usr/local/bin/npx
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm 2>/dev/null || true \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx 2>/dev/null || true \
    && node --version && npm --version

# Create non-root user for better security on HF Spaces
RUN groupadd -r viralmint && useradd -r -g viralmint -d /app -s /sbin/nologin viralmint

WORKDIR /app

# Copy project files
COPY . .

# Ownership for storage dirs that will be created at runtime
RUN mkdir -p /app/storage && chown -R viralmint:viralmint /app

USER viralmint

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Node dependencies and build the frontend
RUN cd frontend \
    && npm install \
    && npm run build \
    && rm -rf node_modules

# Expose HF Spaces default port
EXPOSE 7860

# Health check (optional, helps HF detect readiness)
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:7860/health || exit 1

# Start ViralMint
CMD ["python", "run.py"]