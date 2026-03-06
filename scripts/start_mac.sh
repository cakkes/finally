#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Check .env exists
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "Created .env from .env.example — please add your OPENROUTER_API_KEY"
fi

# Build if needed
if [[ "$1" == "--build" ]] || ! docker image inspect finally:latest >/dev/null 2>&1; then
  echo "Building FinAlly Docker image..."
  docker build -t finally:latest .
fi

# Stop existing container
docker rm -f finally-app 2>/dev/null || true

# Run
docker run -d \
  --name finally-app \
  -v finally-data:/app/db \
  -p 8000:8000 \
  --env-file .env \
  finally:latest

echo ""
echo "FinAlly is running at http://localhost:8000"
echo "  Stop with: ./scripts/stop_mac.sh"

# Open browser on macOS
if command -v open >/dev/null 2>&1; then
  sleep 2
  open http://localhost:8000
fi
