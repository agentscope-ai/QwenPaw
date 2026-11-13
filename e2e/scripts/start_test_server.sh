#!/usr/bin/env bash
# Start an isolated QwenPaw backend for local E2E testing.
#
# Usage:
#   ./e2e/scripts/start_test_server.sh          # foreground
#   ./e2e/scripts/start_test_server.sh --bg      # background (writes PID file)
#
# The instance uses a dedicated working directory and port so it never
# touches your personal QwenPaw data at ~/.qwenpaw.
#
# Stop with:  ./e2e/scripts/stop_test_server.sh
#        or:  Ctrl-C (foreground mode)

set -euo pipefail

# ── Config ──────────────────────────────────────────────────────────
E2E_PORT="${QWENPAW_E2E_PORT:-7077}"
E2E_ROOT="/tmp/qwenpaw-e2e-test-work-dir"
E2E_WORKING_DIR="${E2E_ROOT}/working"
E2E_SECRET_DIR="${E2E_ROOT}/secret"
E2E_BACKUP_DIR="${E2E_ROOT}/backups"
PID_FILE="${E2E_ROOT}/qwenpaw-e2e.pid"

# ── Prepare dirs ────────────────────────────────────────────────────
mkdir -p "$E2E_WORKING_DIR" "$E2E_SECRET_DIR" "$E2E_BACKUP_DIR"

# ── Check port not in use ───────────────────────────────────────────
if lsof -i :"$E2E_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "⚠  Port $E2E_PORT is already in use."
  echo "   If a previous test server is running, stop it first:"
  echo "     ./e2e/scripts/stop_test_server.sh"
  exit 1
fi

echo "Starting isolated QwenPaw for E2E testing..."
echo "  Port:        $E2E_PORT"
echo "  Working dir: $E2E_WORKING_DIR"
echo "  PID file:    $PID_FILE"
echo ""

# ── Export env ──────────────────────────────────────────────────────
export QWENPAW_WORKING_DIR="$E2E_WORKING_DIR"
export QWENPAW_SECRET_DIR="$E2E_SECRET_DIR"
export QWENPAW_BACKUP_DIR="$E2E_BACKUP_DIR"
export QWENPAW_AUTH_ENABLED=false
export PYTHONUNBUFFERED=1

# ── Resolve python/qwenpaw executable ──────────────────────────────
# Try multiple strategies to find a working qwenpaw installation:
# 1. QWENPAW_PYTHON env var (user override)
# 2. `qwenpaw` CLI on PATH
# 3. Project .venv or sibling venvs with qwenpaw installed
# 4. python3 / python with qwenpaw importable
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LAUNCH_CMD=""

_try_python() {
  local py="$1"
  if [ -x "$py" ] && "$py" -c "import qwenpaw" 2>/dev/null; then
    LAUNCH_CMD="$py -m qwenpaw"
    return 0
  fi
  return 1
}

if [ -n "${QWENPAW_PYTHON:-}" ]; then
  _try_python "$QWENPAW_PYTHON" || {
    echo "✗ QWENPAW_PYTHON=$QWENPAW_PYTHON cannot import qwenpaw"
    exit 1
  }
elif command -v qwenpaw &>/dev/null; then
  LAUNCH_CMD="qwenpaw"
else
  # Search common venv locations
  for candidate in \
    "$REPO_ROOT/.venv/bin/python" \
    "$REPO_ROOT/../.venv/bin/python" \
    "$HOME/qwenpaw_space/.venv/bin/python" \
    "$HOME/.qwenpaw-venv/bin/python" \
  ; do
    _try_python "$candidate" && break
  done
  # Last resort: system python
  if [ -z "$LAUNCH_CMD" ]; then
    for cmd in python3 python; do
      if command -v "$cmd" &>/dev/null && "$cmd" -c "import qwenpaw" 2>/dev/null; then
        LAUNCH_CMD="$cmd -m qwenpaw"
        break
      fi
    done
  fi
fi

if [ -z "$LAUNCH_CMD" ]; then
  echo "✗ Cannot find qwenpaw."
  echo "  Set QWENPAW_PYTHON=/path/to/python-with-qwenpaw, or"
  echo "  install with: pip install -e '.[dev]'"
  exit 1
fi

echo "  Using:       $LAUNCH_CMD"

# ── Launch ──────────────────────────────────────────────────────────
run_server() {
  $LAUNCH_CMD app --host 127.0.0.1 --port "$E2E_PORT" --log-level info
}

wait_ready() {
  local deadline=$((SECONDS + 60))
  while [ $SECONDS -lt $deadline ]; do
    if curl -sf "http://localhost:${E2E_PORT}/api/version" >/dev/null 2>&1; then
      echo "✓ Backend ready on port $E2E_PORT"
      return 0
    fi
    sleep 1
  done
  echo "✗ Backend failed to start within 60s"
  return 1
}

if [[ "${1:-}" == "--bg" ]]; then
  # Background mode
  run_server &
  SERVER_PID=$!
  echo "$SERVER_PID" > "$PID_FILE"
  echo "  Server PID:  $SERVER_PID"
  if wait_ready; then
    echo ""
    echo "Run tests with:"
    echo "  cd e2e && QWENPAW_BASE_URL=http://localhost:${E2E_PORT} pytest tests/ -v"
    echo ""
    echo "Stop with:"
    echo "  ./e2e/scripts/stop_test_server.sh"
  else
    kill "$SERVER_PID" 2>/dev/null || true
    rm -f "$PID_FILE"
    exit 1
  fi
else
  # Foreground mode (Ctrl-C to stop)
  echo "(Press Ctrl-C to stop)"
  echo ""
  run_server
fi
