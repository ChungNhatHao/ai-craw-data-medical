#!/usr/bin/env bash
set -euo pipefail

smoke_port="${SMOKE_PORT:-8765}"
.venv/bin/uvicorn main:app --host 127.0.0.1 --port "${smoke_port}" >/tmp/aicrawler-uvicorn.log 2>&1 &
server_pid=$!

cleanup() {
  kill "${server_pid}" 2>/dev/null || true
  wait "${server_pid}" 2>/dev/null || true
}
trap cleanup EXIT

for _ in {1..50}; do
  if curl -fsS "http://127.0.0.1:${smoke_port}/api/v1/health/live" \
    >/dev/null 2>&1; then
    break
  fi
  sleep 0.1
done

curl -fsS "http://127.0.0.1:${smoke_port}/api/v1/health/live"
printf "\n"
curl -fsS "http://127.0.0.1:${smoke_port}/api/v1/health/ready"
printf "\n"
