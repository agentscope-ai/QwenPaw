#!/usr/bin/env bash
# Stop the isolated QwenPaw E2E backend started by start_test_server.sh.

set -euo pipefail

E2E_ROOT="/tmp/qwenpaw-e2e-test-work-dir"
PID_FILE="${E2E_ROOT}/qwenpaw-e2e.pid"

if [ ! -f "$PID_FILE" ]; then
  echo "No PID file found at $PID_FILE — server may not be running."
  exit 0
fi

PID=$(cat "$PID_FILE")

if kill -0 "$PID" 2>/dev/null; then
  echo "Stopping QwenPaw E2E server (PID $PID)..."
  kill -INT "$PID" 2>/dev/null || true
  # Wait up to 10s for graceful shutdown
  for i in $(seq 1 10); do
    kill -0 "$PID" 2>/dev/null || break
    sleep 1
  done
  # Force kill if still alive
  if kill -0 "$PID" 2>/dev/null; then
    echo "Graceful shutdown timed out, force-killing..."
    kill -9 "$PID" 2>/dev/null || true
  fi
  echo "✓ Server stopped."
else
  echo "Process $PID is not running (stale PID file)."
fi

rm -f "$PID_FILE"
