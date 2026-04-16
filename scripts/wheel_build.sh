#!/usr/bin/env bash
# Build a full wheel package including the latest console frontend.
# Run from repo root: bash scripts/wheel_build.sh
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

CONSOLE_DIR="$REPO_ROOT/console"
CONSOLE_DEST="$REPO_ROOT/src/qwenpaw/console"

echo "[wheel_build] Building console frontend..."
if ! command -v pnpm &>/dev/null; then
    if command -v npm &>/dev/null; then
        echo "pnpm not found, installing via npm..."
        npm install -g pnpm
    else
        echo "pnpm not found and npm is also not available. Install Node.js first." >&2
        exit 1
    fi
fi

(cd "$CONSOLE_DIR" && pnpm install)
(cd "$CONSOLE_DIR" && pnpm run build)

echo "[wheel_build] Copying console/dist/* -> src/qwenpaw/console/..."
rm -rf "$CONSOLE_DEST"/*

mkdir -p "$CONSOLE_DEST"
cp -R "$CONSOLE_DIR/dist/"* "$CONSOLE_DEST/"

echo "[wheel_build] Building wheel + sdist..."
python3 -m pip install --quiet build
rm -rf dist/*
python3 -m build --outdir dist .

echo "[wheel_build] Done. Wheel(s) in: $REPO_ROOT/dist/"
