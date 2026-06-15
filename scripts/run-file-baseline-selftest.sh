#!/usr/bin/env bash
# Run File baseline self-test net (wiring + backend + frontend).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$REPO_ROOT"
exec python3 "$SCRIPT_DIR/run-file-baseline-selftest.py" "$@"
