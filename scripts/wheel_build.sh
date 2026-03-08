#!/usr/bin/env bash
# Build a full wheel package including the latest console frontend.
# Run from repo root: bash scripts/wheel_build.sh
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

CONSOLE_DIR="$REPO_ROOT/console"
CONSOLE_DEST="$REPO_ROOT/src/copaw/console"

echo "[wheel_build] Building console frontend..."
(cd "$CONSOLE_DIR" && npm ci)
(cd "$CONSOLE_DIR" && npm run build)

echo "[wheel_build] Building wheel + sdist..."
rm -rf dist/*
if command -v uv &>/dev/null; then
    uv pip install --quiet build
    uv build --out-dir dist .
else
    python3 -m pip install --quiet build
    python3 -m build --outdir dist .
fi

echo "[wheel_build] Done. Wheel(s) in: $REPO_ROOT/dist/"
