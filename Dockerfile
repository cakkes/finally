# Stage 1: Build frontend
FROM node:20-slim AS frontend-build
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python backend
FROM python:3.12-slim AS final

# Install curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Install Python deps first (cache layer)
COPY backend/pyproject.toml backend/uv.lock ./
RUN touch README.md && uv sync --frozen --no-dev

# Copy backend source
COPY backend/ ./

# Copy frontend static build to where backend expects it
# backend/app/main.py resolves STATIC_DIR as ../../frontend/out relative to itself
# main.py is at /app/app/main.py, so STATIC_DIR = /frontend/out
COPY --from=frontend-build /build/out /frontend/out

# Create db directory
RUN mkdir -p /app/db

EXPOSE 8000

ENV DB_PATH=/app/db/finally.db

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
