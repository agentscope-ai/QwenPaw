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

echo "[wheel_build] Copying console/dist/* -> src/copaw/console/..."
rm -rf "$CONSOLE_DEST"/*

mkdir -p "$CONSOLE_DEST"
cp -R "$CONSOLE_DIR/dist/"* "$CONSOLE_DEST/"

echo "[wheel_build] Building wheel + sdist..."
PYTHON_BIN="${PYTHON_BIN:-python3}"
BUILD_VENV_DIR="${WHEEL_BUILD_VENV:-$REPO_ROOT/.wheelshim/build-venv}"
BUILD_PY="$BUILD_VENV_DIR/bin/python"

if [ ! -x "$BUILD_PY" ]; then
  echo "[wheel_build] Creating isolated build venv: $BUILD_VENV_DIR"
  "$PYTHON_BIN" -m venv "$BUILD_VENV_DIR"
fi

"$BUILD_PY" -m pip install --quiet --upgrade pip build
rm -rf dist/*
"$BUILD_PY" -m build --outdir dist .

echo "[wheel_build] Done. Wheel(s) in: $REPO_ROOT/dist/"
