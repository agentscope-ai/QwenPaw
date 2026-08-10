#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DATAPAW_SOURCE_DIR="${DATAPAW_SOURCE_DIR:-$HOME/dev/QwenPaw-Data}"
QWENPAW_BIN="${QWENPAW_BIN:-qwenpaw}"
QWENPAW_HOST="${QWENPAW_HOST:-127.0.0.1}"
QWENPAW_PORT="${QWENPAW_PORT:-8089}"
if [[ -n "${QWENPAW_WORKING_DIR:-}" ]]; then
  WORKING_DIR="$QWENPAW_WORKING_DIR"
elif [[ -d "$HOME/.copaw" ]]; then
  WORKING_DIR="$HOME/.copaw"
else
  WORKING_DIR="$HOME/.qwenpaw"
fi
WORKING_DIR="${WORKING_DIR/#\~/$HOME}"

"$SCRIPT_DIR/setup-dev.sh"

echo "==> Building the QwenPaw-Data native UI"
(cd "$APP_DIR/ui" && npm install --ignore-scripts --no-audit --no-fund && npm run build)

STAGE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/datapaw-app.XXXXXX")"
trap 'rm -rf "$STAGE_DIR"' EXIT
mkdir -p "$STAGE_DIR/backend" "$STAGE_DIR/ui/dist" \
  "$STAGE_DIR/agents/datapaw/en"
cp "$APP_DIR/plugin.json" "$APP_DIR/requirements.txt" "$APP_DIR/__init__.py" "$STAGE_DIR/"
cp "$APP_DIR/backend/__init__.py" "$APP_DIR/backend/context_gateway.py" \
  "$APP_DIR/backend/main.py" "$APP_DIR/backend/runtime.py" \
  "$STAGE_DIR/backend/"
cp "$APP_DIR/agents/datapaw/en/PROFILE.md" \
  "$APP_DIR/agents/datapaw/en/SOUL.md" "$STAGE_DIR/agents/datapaw/en/"
cp "$APP_DIR/ui/dist/index.js" "$APP_DIR/ui/dist/index.js.map" "$STAGE_DIR/ui/dist/"
if [[ -d "$APP_DIR/ui/dist/app" ]]; then
  cp -R "$APP_DIR/ui/dist/app" "$STAGE_DIR/ui/dist/"
fi

echo "==> Installing the staged PawApp"
"$QWENPAW_BIN" --host "$QWENPAW_HOST" --port "$QWENPAW_PORT" \
  plugin install "$STAGE_DIR" --force

INSTALLED_APP="$WORKING_DIR/plugins/datapaw"
if [[ ! -d "$INSTALLED_APP" ]]; then
  echo "Installed QwenPaw-Data directory was not found: $INSTALLED_APP" >&2
  exit 1
fi

mkdir -p "$INSTALLED_APP/.datapaw-dev"
link_path() {
  local source_path="$1"
  local target_path="$2"
  if [[ -e "$target_path" && ! -L "$target_path" ]]; then
    echo "Refusing to replace non-symlink path: $target_path" >&2
    exit 1
  fi
  ln -sfn "$source_path" "$target_path"
}

link_path "$DATAPAW_SOURCE_DIR/.venv" "$INSTALLED_APP/.venv-datapaw"
link_path "$DATAPAW_SOURCE_DIR" "$INSTALLED_APP/.datapaw-dev/source"
link_path \
  "$DATAPAW_SOURCE_DIR/packages/datapaw-skills/skills" \
  "$INSTALLED_APP/.datapaw-dev/skills"

echo "==> QwenPaw-Data installed. Start QwenPaw and open /apps/datapaw"
