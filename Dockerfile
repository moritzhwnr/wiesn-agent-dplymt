# ── Stage 1: Build frontend ──
FROM node:22-slim AS frontend
WORKDIR /app/web
COPY web/package.json web/package-lock.json* ./
RUN npm ci
COPY web/ .
RUN npm run build

# ── Stage 2: Python runtime ──
FROM python:3.12-slim

# System deps for Playwright Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    libxshmfence1 libx11-xcb1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python dependencies
COPY pyproject.toml README.md LICENSE ./
COPY src/ src/
RUN pip install --no-cache-dir uv \
    && uv pip install --system ".[web]" \
    && playwright install chromium

# Copy built frontend from stage 1
COPY --from=frontend /app/web/dist web/dist

# Config template
COPY config.example.yaml ./

# Data directory
RUN mkdir -p data screenshots

EXPOSE 5000

# Use config.yaml if mounted, otherwise fall back to example
CMD ["sh", "-c", "test -f config.yaml || cp config.example.yaml config.yaml; wiesn-agent web --host 0.0.0.0"]
