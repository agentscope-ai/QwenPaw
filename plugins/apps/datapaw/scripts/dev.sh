#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$APP_DIR/../../.." && pwd)"
DATAPAW_SOURCE_DIR="${DATAPAW_SOURCE_DIR:-$HOME/dev/QwenPaw-Data}"
# Prefer the workspace CLI: a PATH-installed qwenpaw may come from another
# checkout whose plugin validation rejects this app's imports.
if [[ -z "${QWENPAW_BIN:-}" && -x "$REPO_ROOT/.venv/bin/qwenpaw" ]]; then
  QWENPAW_BIN="$REPO_ROOT/.venv/bin/qwenpaw"
fi
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
LOGO_ASSET="$APP_DIR/ui/dist/app/logo-mark-v4.png"
if [[ ! -f "$LOGO_ASSET" ]]; then
  echo "Required QwenPaw-Data logo asset was not built: $LOGO_ASSET" >&2
  exit 1
fi
mkdir -p "$STAGE_DIR/ui/dist/app"
cp "$LOGO_ASSET" "$STAGE_DIR/ui/dist/app/"

CONTEXT_CONSOLE_DIR="$APP_DIR/ui/dist/context-console"
if [[ -d "$CONTEXT_CONSOLE_DIR" ]]; then
  cp -R "$CONTEXT_CONSOLE_DIR" "$STAGE_DIR/ui/dist/context-console"
else
  echo "NOTE: embedded Context console not found; run" \
    "scripts/sync-context-ui.sh to vendor it." >&2
fi

# Hot-install against the configured instance. The CLI's hot-install path
# routes via config.json's last_api (ignoring --host/--port), which can point
# at a different running QwenPaw instance; talk to the API directly instead.
install_plugin() {
  local source_path="$1"
  local response
  if ! response=$(curl -sf --max-time 180 \
    -X POST "http://$QWENPAW_HOST:$QWENPAW_PORT/api/plugins/install" \
    -H 'Content-Type: application/json' \
    -d "{\"source\":\"$source_path\",\"force\":true}"); then
    echo "Hot-install failed against" \
      "http://$QWENPAW_HOST:$QWENPAW_PORT — is QwenPaw running there?" >&2
    exit 1
  fi
  echo "✅ Hot-installed: $response" | head -c 200
  echo
}

echo "==> Installing the staged PawApp"
install_plugin "$STAGE_DIR"

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

# The first install imports the backend before the .datapaw-dev symlinks
# exist, so skills resolve as unavailable. Reinstalling from the installed
# directory itself skips the copy (source == target) and only re-imports,
# which picks the symlinks up.
echo "==> Reloading the app so it picks up the dev symlinks"
install_plugin "$INSTALLED_APP"

echo "==> QwenPaw-Data installed. Start QwenPaw and open /apps/datapaw"
