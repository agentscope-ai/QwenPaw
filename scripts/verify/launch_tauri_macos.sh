#!/usr/bin/env bash
# Unpack, launch the Tauri macOS shell, and wait for the backend to be ready.
# Outputs BASE_URL to $GITHUB_ENV for subsequent steps.
set -euo pipefail

# 1. Unpack the freshly built Tauri zip.
echo "[launch_tauri_macos] Unpacking zip..."
mkdir -p dist/verify-tauri
unzip -q dist/QwenPaw-Tauri-*-macOS.zip -d dist/verify-tauri
APP="$(find dist/verify-tauri -maxdepth 3 -name '*.app' -type d | head -1)"
if [ -z "$APP" ]; then
  echo "::error::Tauri .app not found inside zip"
  exit 1
fi
echo "[launch_tauri_macos] Found app: $APP"

# 2. Remove macOS quarantine (CI download marks it).
xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true

# 3. Pre-delete BOOTSTRAP.md so the agent answers in plain QA mode.
mkdir -p "$HOME/.qwenpaw/workspaces/default"
rm -f "$HOME/.qwenpaw/workspaces/default/BOOTSTRAP.md"

# 4. Launch the full Tauri shell (matches real user double-click).
echo "[launch_tauri_macos] Launching Tauri shell..."
open "$APP"
echo "[launch_tauri_macos] open exit=$?"
sleep 3
echo "[launch_tauri_macos] Process snapshot after launch:"
ps -ef | grep -iE "qwenpaw|tauri" | grep -v grep || echo "  (no matching processes)"

# 5. Wait for the sidecar to write the port file and respond.
#    The sidecar writes desktop_port at WORKING_DIR root (~/.qwenpaw),
#    not inside the workspace dir.
PORT_FILE="$HOME/.qwenpaw/desktop_port"
PORT=""
for i in $(seq 1 60); do
  if [ -f "$PORT_FILE" ]; then
    PORT="$(cat "$PORT_FILE" | tr -d '[:space:]')"
    if [ -n "$PORT" ] && curl -sf "http://127.0.0.1:$PORT/api/version" >/dev/null; then
      echo "[launch_tauri_macos] Tauri app ready on port $PORT after ~$((i*2))s"
      break
    fi
  fi
  if [ "$i" = "60" ]; then
    echo "::error::Tauri app did not start within 120s"
    echo "[debug] PORT_FILE=$PORT_FILE exists=$([ -f "$PORT_FILE" ] && echo yes || echo no)"
    echo "[debug] WORKING_DIR (~/.qwenpaw) contents:"
    ls -la "$HOME/.qwenpaw/" 2>/dev/null || echo "  (missing)"
    echo "[debug] All qwenpaw-related files under HOME (top 30):"
    find "$HOME/.qwenpaw" -maxdepth 4 -type f 2>/dev/null | head -30 || true
    echo "[debug] desktop.log tail (if exists):"
    tail -50 "$HOME/.qwenpaw/desktop.log" 2>/dev/null || echo "  (no desktop.log)"
    echo "[debug] Process list:"
    ps -ef | grep -iE "qwenpaw|tauri" | grep -v grep || echo "  (no matching processes)"
    exit 1
  fi
  sleep 2
done

export BASE_URL="http://127.0.0.1:$PORT"
echo "BASE_URL=$BASE_URL" >> "$GITHUB_ENV"
echo "$BASE_URL"
