#!/usr/bin/env bash
# Compatibility entry point for callers that stage the old Context URL.
set -euo pipefail
ui_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../ui" && pwd)"
mkdir -p "$ui_dir/public/context-console"
cp "$ui_dir/compat/context-console/index.html" "$ui_dir/public/context-console/"
