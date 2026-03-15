#!/usr/bin/env bash
# Build a full wheel package including the latest console frontend.
# Run from repo root: bash scripts/wheel_build.sh
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

CONSOLE_DIR="$REPO_ROOT/console"
CONSOLE_DEST="$REPO_ROOT/src/copaw/console"

# Prefer workspace virtualenv interpreter, then active python, then python3.
if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
	PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
elif command -v python >/dev/null 2>&1; then
	PYTHON_BIN="python"
else
	PYTHON_BIN="python3"
fi

echo "[wheel_build] Building console frontend..."
(cd "$CONSOLE_DIR" && npm ci)
(cd "$CONSOLE_DIR" && npm run build)

echo "[wheel_build] Copying console/dist/* -> src/copaw/console/..."
rm -rf "$CONSOLE_DEST"/*

mkdir -p "$CONSOLE_DEST"
cp -R "$CONSOLE_DIR/dist/"* "$CONSOLE_DEST/"

echo "[wheel_build] Building wheel + sdist..."
"$PYTHON_BIN" -m pip install --quiet build
rm -rf dist/*
"$PYTHON_BIN" -m build --outdir dist .

echo "[wheel_build] Done. Wheel(s) in: $REPO_ROOT/dist/"
