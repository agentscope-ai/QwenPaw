#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# Install the qwenpaw-data runtime from PyPI into the current Python environment.
#
# This is the out-of-the-box path: it does not require a QwenPaw-Data source
# workspace, uv, or any development tooling. It simply pip-installs the four
# runtime packages that the qwenpaw-data plugin needs to start its managed context
# service.
#
# If you prefer to run against an existing Context service, set
# QWENPAW_DATA_CONTEXT_MODE=external instead of installing the runtime locally.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

PYTHON_BIN="${QWENPAW_DATA_CONTEXT_PYTHON:-${PYTHON:-$(command -v python3 || command -v python)}}"
if [[ -z "$PYTHON_BIN" ]]; then
  echo "ERROR: no Python interpreter found. Set PYTHON or QWENPAW_DATA_CONTEXT_PYTHON." >&2
  exit 1
fi

echo "==> Installing qwenpaw-data runtime packages with $PYTHON_BIN"
"$PYTHON_BIN" -m pip install --upgrade \
  "qwenpaw-data-context>=0.1,<0.2" \
  "qwenpaw-data-host-core>=0.1,<0.2" \
  "qwenpaw-data-cli>=0.1,<0.2" \
  "qwenpaw-data-skills>=0.1,<0.2"

echo ""
echo "==> Installed versions:"
for package_name in qwenpaw-data-context qwenpaw-data-host-core qwenpaw-data-cli qwenpaw-data-skills; do
  "$PYTHON_BIN" -c \
    'from importlib.metadata import version; import sys; print(f"  {sys.argv[1]}=={version(sys.argv[1])}")' \
    "$package_name"
done

echo ""
echo "==> Verifying context service entry point"
"$PYTHON_BIN" -c "import context_manager.api.server"

echo ""
echo "QwenPaw Data runtime is ready. Start QwenPaw with the qwenpaw-data plugin enabled."
echo "To use an external Context service instead, set:"
echo "  export QWENPAW_DATA_CONTEXT_MODE=external"
echo "  export QWENPAW_DATA_CONTEXT_URL=<context-service-url>"
echo "  export QWENPAW_DATA_CONTEXT_TOKEN=<token>"
