#!/usr/bin/env bash
# Build optional Harness frontends against the actual public host SDK package.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SDK_DIR="${REPO_ROOT}/src/qwenpaw/plugins/frontend"

for frontend_dir in "${REPO_ROOT}"/plugins/harness/*/frontend; do
    [[ -d "$frontend_dir" ]] || continue
    vendor="$(basename "$(dirname "$frontend_dir")")"
    if [[ "$vendor" == codex || "$vendor" == qoder ]]; then
        python "${REPO_ROOT}/scripts/pack/sync_harness_helpers.py" \
            --check --plugin "$vendor"
    fi
    npm --prefix "$frontend_dir" install --include=dev --no-save \
        --package-lock=false "$SDK_DIR"
    npm --prefix "$frontend_dir" run build
done
