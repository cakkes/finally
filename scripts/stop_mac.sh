#!/usr/bin/env bash
docker stop finally-app 2>/dev/null && echo "Stopped FinAlly" || echo "FinAlly was not running"
docker rm finally-app 2>/dev/null || true
echo "Data volume preserved. Run ./scripts/start_mac.sh to restart."
