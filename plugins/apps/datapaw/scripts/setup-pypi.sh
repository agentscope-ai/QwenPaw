#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# Install the datapaw runtime from PyPI into the current Python environment.
#
# This is the out-of-the-box path: it does not require a QwenPaw-Data source
# workspace, uv, or any development tooling. It simply pip-installs the four
# runtime packages that the datapaw plugin needs to start its managed context
# service.
#
# If you prefer to run against an existing Context service, set
# DATAPAW_CONTEXT_MODE=external instead of installing the runtime locally.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

PYTHON_BIN="${DATAPAW_CONTEXT_PYTHON:-${PYTHON:-$(command -v python3 || command -v python)}}"
if [[ -z "$PYTHON_BIN" ]]; then
  echo "ERROR: no Python interpreter found. Set PYTHON or DATAPAW_CONTEXT_PYTHON." >&2
  exit 1
fi

echo "==> Installing datapaw runtime packages with $PYTHON_BIN"
"$PYTHON_BIN" -m pip install --upgrade \
  "datapaw-context>=0.2,<0.3" \
  "datapaw-host-core>=0.2,<0.3" \
  "datapaw-cli>=0.2,<0.3" \
  "datapaw-skills>=0.2,<0.3"

echo ""
echo "==> Installed versions:"
for package_name in datapaw-context datapaw-host-core datapaw-cli datapaw-skills; do
  "$PYTHON_BIN" -c \
    'from importlib.metadata import version; import sys; print(f"  {sys.argv[1]}=={version(sys.argv[1])}")' \
    "$package_name"
done

echo ""
echo "==> Verifying context service entry point"
"$PYTHON_BIN" -c "import context_manager.api.server"

echo ""
echo "Datapaw runtime is ready. Start QwenPaw with the datapaw plugin enabled."
echo "To use an external Context service instead, set:"
echo "  export DATAPAW_CONTEXT_MODE=external"
echo "  export DATAPAW_CONTEXT_URL=<context-service-url>"
echo "  export DATAPAW_CONTEXT_TOKEN=<token>"
