#!/usr/bin/env bash
# Launch the built Linux desktop app under Xvfb and wait for its backend.
# Outputs BASE_URL to $GITHUB_ENV for subsequent verification steps.
set -euo pipefail

LOG_DIR="${RUNNER_TEMP:-/tmp}"
STDOUT_LOG="${LOG_DIR}/qwenpaw-desktop-stdout.log"
STDERR_LOG="${LOG_DIR}/qwenpaw-desktop-stderr.log"

ARTIFACT="$(ls dist/QwenPaw-Tauri-*-linux-*.AppImage 2>/dev/null | head -1 || true)"
if [ -z "${ARTIFACT}" ]; then
  echo "::error::No Linux AppImage found under dist/"
  ls -la dist/ 2>/dev/null || true
  exit 1
fi
chmod +x "${ARTIFACT}"

echo "[launch_tauri_linux] launching ${ARTIFACT}"
# APPIMAGE_EXTRACT_AND_RUN avoids requiring FUSE on CI runners.
# The compositing switches keep WebKit usable on a software-rendered X server.
xvfb-run -a -s "-screen 0 1600x1000x24" \
  env APPIMAGE_EXTRACT_AND_RUN=1 \
      WEBKIT_DISABLE_COMPOSITING_MODE=1 \
      WEBKIT_DISABLE_DMABUF_RENDERER=1 \
      "${ARTIFACT}" \
  > "${STDOUT_LOG}" 2> "${STDERR_LOG}" &
LAUNCH_PID=$!
echo "[launch_tauri_linux] pid=${LAUNCH_PID}"

PORT_FILE="${HOME}/.qwenpaw/desktop_port"
PORT=""
for i in $(seq 1 90); do
  if [ -f "${PORT_FILE}" ]; then
    PORT="$(tr -d '[:space:]' < "${PORT_FILE}")"
    if [ -n "${PORT}" ] && curl -sf "http://127.0.0.1:${PORT}/api/version" >/dev/null; then
      echo "[launch_tauri_linux] ready on port ${PORT} after ~$((i * 2))s"
      break
    fi
  fi
  if [ "${i}" = "90" ]; then
    echo "::error::Linux desktop app did not start within 180s"
    echo "[debug] port file: ${PORT_FILE} exists=$([ -f "${PORT_FILE}" ] && echo yes || echo no)"
    echo "[debug] stdout tail:"
    tail -40 "${STDOUT_LOG}" 2>/dev/null || true
    echo "[debug] stderr tail:"
    tail -40 "${STDERR_LOG}" 2>/dev/null || true
    pkill -f qwenpaw-desktop 2>/dev/null || true
    exit 1
  fi
  if ! kill -0 "${LAUNCH_PID}" 2>/dev/null; then
    echo "::error::Linux desktop app exited during startup"
    tail -40 "${STDERR_LOG}" 2>/dev/null || true
    exit 1
  fi
  sleep 2
done

# Auto-init drops BOOTSTRAP.md on first launch; remove it so the verifier
# drives the agent in normal QA mode.
rm -f "${HOME}/.qwenpaw/workspaces/default/BOOTSTRAP.md"

export BASE_URL="http://127.0.0.1:${PORT}"
echo "BASE_URL=${BASE_URL}" >> "${GITHUB_ENV:-/dev/stdout}"
echo "${BASE_URL}"
