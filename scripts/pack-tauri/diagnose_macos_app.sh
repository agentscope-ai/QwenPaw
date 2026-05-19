#!/usr/bin/env bash
# Diagnose the packaged macOS Tauri app without launching the GUI.
#
# The check verifies code signatures, prints signing metadata for the app and
# backend sidecar, then starts the packaged sidecar and probes the endpoints
# that exercise the desktop settings and local Whisper status paths.

set -euo pipefail

APP_PATH="${1:?Usage: diagnose_macos_app.sh <QwenPaw Desktop.app>}"
PORT="${QWENPAW_DIAG_PORT:-19088}"
LOG_FILE="${QWENPAW_DIAG_LOG:-tauri-backend-smoke.log}"
if [[ "${LOG_FILE}" != /* ]]; then
    LOG_FILE="$(pwd)/${LOG_FILE}"
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "ERROR: macOS diagnostics must run on Darwin"
    exit 1
fi

if [[ ! -d "${APP_PATH}" ]]; then
    echo "ERROR: app bundle not found: ${APP_PATH}"
    exit 1
fi

BACKEND="${APP_PATH}/Contents/Resources/binaries/qwenpaw-backend/qwenpaw-backend"
if [[ ! -x "${BACKEND}" ]]; then
    echo "ERROR: backend sidecar not executable: ${BACKEND}"
    exit 1
fi
BACKEND_DIR="$(dirname "${BACKEND}")"

echo "== macOS app signature verification =="
codesign --verify --deep --strict --verbose=4 "${APP_PATH}"
codesign -dv --verbose=4 "${APP_PATH}" 2>&1 || true

echo ""
echo "== backend sidecar signature =="
codesign --verify --verbose=4 "${BACKEND}"
codesign -dv --verbose=4 "${BACKEND}" 2>&1 || true

echo ""
echo "== bundled Mach-O signature scan =="
checked=0
while IFS= read -r -d '' path; do
    if file -b "${path}" | grep -q "Mach-O"; then
        codesign --verify --verbose=2 "${path}"
        checked=$((checked + 1))
    fi
done < <(find "${APP_PATH}" -type f -print0)
echo "Verified ${checked} bundled Mach-O files"

echo ""
echo "== backend sidecar smoke test =="
rm -f "${LOG_FILE}"

cleanup() {
    if [[ -n "${BACKEND_PID:-}" ]] && kill -0 "${BACKEND_PID}" 2>/dev/null; then
        kill "${BACKEND_PID}" 2>/dev/null || true
        wait "${BACKEND_PID}" 2>/dev/null || true
    fi
}
trap cleanup EXIT

(
    export QWENPAW_DESKTOP_APP=1
    export QWENPAW_DESKTOP_PORT="${PORT}"
    export PYTHONUTF8=1
    export PYTHONIOENCODING=utf-8
    cd "${BACKEND_DIR}"
    "${BACKEND}"
) > "${LOG_FILE}" 2>&1 &
BACKEND_PID=$!

echo "Started backend pid=${BACKEND_PID} port=${PORT}"

ready=0
for _ in $(seq 1 120); do
    if ! kill -0 "${BACKEND_PID}" 2>/dev/null; then
        echo "ERROR: backend exited before becoming ready"
        cat "${LOG_FILE}" || true
        exit 1
    fi
    if curl -fsS "http://127.0.0.1:${PORT}/api/version" >/tmp/qwenpaw-version.json; then
        ready=1
        break
    fi
    sleep 1
done

if [[ "${ready}" != "1" ]]; then
    echo "ERROR: backend did not become ready"
    cat "${LOG_FILE}" || true
    exit 1
fi

echo "version:"
cat /tmp/qwenpaw-version.json
echo ""

echo "local whisper status:"
curl -fsS "http://127.0.0.1:${PORT}/api/workspace/local-whisper-status"
echo ""

echo "transcription providers:"
curl -fsS "http://127.0.0.1:${PORT}/api/workspace/transcription-providers"
echo ""

if ! kill -0 "${BACKEND_PID}" 2>/dev/null; then
    echo "ERROR: backend exited during diagnostics"
    cat "${LOG_FILE}" || true
    exit 1
fi

echo "Backend diagnostics passed"
