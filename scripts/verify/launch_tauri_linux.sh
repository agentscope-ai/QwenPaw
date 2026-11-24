#!/usr/bin/env bash
# Keep the packaged window, native driver and shared verifier on one display.
set -euo pipefail
xvfb-run -a -s "-screen 0 1600x1000x24" \
  python scripts/verify/verify_tauri_linux.py "$@"
