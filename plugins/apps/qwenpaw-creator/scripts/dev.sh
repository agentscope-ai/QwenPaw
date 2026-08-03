#!/usr/bin/env bash
# dev.sh — Single entry point for creator plugin development.
#
# Usage:
#   scripts/dev.sh            # watch mode (default): hot-feedback loop.
#                             # Auto-installs first if not installed yet.
#   scripts/dev.sh install    # (re)install once: full build + clean staged
#                             # copy + `qwenpaw plugin install --force`.
#                             # Needed after plugin.json / requirements.txt
#                             # changes (they affect the registered manifest
#                             # and pip deps, not just synced files).
#
# Watch mode:
#   - frontend: `vite build --watch` rebuilds ui/dist incrementally; changes
#     are synced into the installed copy — hard-refresh the browser.
#   - backend:  *.py changes are synced and hot-reloaded via the plugins
#     install API — fully automatic, no restart.
#
# Environment:
#   QWENPAW_BIN          qwenpaw executable (default: qwenpaw on PATH)
#   QWENPAW_PYTHON       Python used by QwenPaw (default: python3 on PATH)
#   QWENPAW_WORKING_DIR  working dir of the target instance (default ~/.qwenpaw)
#   QWENPAW_PORT         API port for backend hot reload (default 8088)
#
# Why stage instead of installing the plugin dir directly? The dir doubles
# as the frontend dev workspace: after a build it contains ui/node_modules
# (~300MB), and QwenPaw's installer copies everything with no ignore rules,
# blowing past the CLI's 120s hot-install timeout.

set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
QWENPAW_BIN="${QWENPAW_BIN:-qwenpaw}"
QWENPAW_PYTHON="${QWENPAW_PYTHON:-python3}"
WORKING_DIR="${QWENPAW_WORKING_DIR:-$HOME/.qwenpaw}"
WORKING_DIR="${WORKING_DIR/#\~/$HOME}"

install_plugin() {
  echo "==> Building creator UI..."
  (cd "$PLUGIN_DIR/ui" && npm run build)

  STAGE_DIR="${TMPDIR:-/tmp}/qwenpaw-creator-staged"
  echo "==> Staging runtime files to $STAGE_DIR ..."
  rm -rf "$STAGE_DIR"
  mkdir -p "$STAGE_DIR/ui"
  cp "$PLUGIN_DIR/plugin.json" "$STAGE_DIR/"
  cp "$PLUGIN_DIR/requirements.txt" "$STAGE_DIR/"
  [ -f "$PLUGIN_DIR/__init__.py" ] && cp "$PLUGIN_DIR/__init__.py" "$STAGE_DIR/"
  rsync -a --exclude '__pycache__' --exclude '*.pyc' \
    "$PLUGIN_DIR/backend/" "$STAGE_DIR/backend/"
  rsync -a "$PLUGIN_DIR/ui/dist/" "$STAGE_DIR/ui/dist/"
  du -sh "$STAGE_DIR" | awk '{print "==> Staged package size: " $1}'

  echo "==> Installing via qwenpaw plugin install --force ..."
  "$QWENPAW_BIN" plugin install "$STAGE_DIR" --force
  echo "==> Ensuring Playwright Chromium is installed for motion overlays ..."
  "$QWENPAW_PYTHON" -m playwright install chromium
  echo "==> Installed. If a console page is already open, hard-refresh it."
}

watch_plugin() {
  if [ ! -d "$WORKING_DIR/plugins/qwenpaw-creator" ]; then
    echo "==> Plugin not installed yet — installing first ..."
    install_plugin
  fi

  echo "==> Starting vite build --watch (ui/) ..."
  (cd "$PLUGIN_DIR/ui" && npx vite build --watch) &
  VITE_PID=$!
  trap 'kill "$VITE_PID" 2>/dev/null || true' EXIT

  python3 -u "$PLUGIN_DIR/scripts/dev_watch.py"
}

case "${1:-watch}" in
  install) install_plugin ;;
  watch)   watch_plugin ;;
  *)
    echo "Usage: $0 [install|watch]" >&2
    exit 1
    ;;
esac
