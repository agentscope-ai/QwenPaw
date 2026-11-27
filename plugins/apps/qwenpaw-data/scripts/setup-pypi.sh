#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# Install the published runtime for the managed Context and Engine services.
#
# If you prefer to run against an existing Context service, set
# QWENPAW_DATA_CONTEXT_MODE=external instead of installing the runtime locally.

set -euo pipefail

PYTHON_BIN="${QWENPAW_DATA_CONTEXT_PYTHON:-${PYTHON:-$(command -v python3 || command -v python)}}"
if [[ -z "$PYTHON_BIN" ]]; then
  echo "ERROR: no Python interpreter found. Set PYTHON or QWENPAW_DATA_CONTEXT_PYTHON." >&2
  exit 1
fi

echo "==> Installing qwenpaw-data runtime packages with $PYTHON_BIN"
"$PYTHON_BIN" -m pip install --upgrade \
  "qwenpaw-data-context==0.4.1" \
  "qwenpaw-data-host-core[service]==0.4.1" \
  "qwenpaw-data-cli==0.4.1" \
  "qwenpaw-data-skills==0.4.1"

echo ""
echo "==> Installed versions:"
for package_name in qwenpaw-data-context qwenpaw-data-host-core qwenpaw-data-cli qwenpaw-data-skills; do
  "$PYTHON_BIN" -c \
    'from importlib.metadata import version; import sys; print(f"  {sys.argv[1]}=={version(sys.argv[1])}")' \
    "$package_name"
done

echo ""
echo "==> Verifying Context and engine service entry points"
"$PYTHON_BIN" - <<'PY'
from importlib.util import find_spec

for module in ("context_manager.api.server", "qwenpaw_data.host.core.api.app"):
    if find_spec(module) is None:
        raise SystemExit(f"Missing runtime entry point: {module}")
PY

echo ""
echo "QwenPaw Data runtime is ready. Start QwenPaw with the qwenpaw-data plugin enabled."
echo "For external Engine, Context, and Auth settings, see the QwenPaw Data plugin README."
