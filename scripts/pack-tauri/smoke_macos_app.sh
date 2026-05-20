#!/usr/bin/env bash
# Smoke-test the packaged macOS Tauri app without launching the GUI.
#
# This verifies the app signature state, starts the bundled Python sidecar, and
# probes the endpoints that the desktop shell needs during startup/settings.

set -euo pipefail

APP_PATH="${1:?Usage: smoke_macos_app.sh <QwenPaw Desktop.app>}"
PORT="${QWENPAW_SMOKE_PORT:-19088}"
LOG_FILE="${QWENPAW_SMOKE_LOG:-}"

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "ERROR: macOS smoke tests must run on Darwin"
    exit 1
fi

if [[ ! -d "${APP_PATH}" ]]; then
    echo "ERROR: app bundle not found: ${APP_PATH}"
    exit 1
fi

if [[ -z "${LOG_FILE}" ]]; then
    LOG_FILE="$(mktemp -t qwenpaw-tauri-backend.XXXXXX.log)"
elif [[ "${LOG_FILE}" != /* ]]; then
    LOG_FILE="$(pwd)/${LOG_FILE}"
fi
PYTHON_LOG_FILE="${LOG_FILE}.python.log"

APP_PARENT="$(cd "$(dirname "${APP_PATH}")" && pwd)"
APP_PATH="${APP_PARENT}/$(basename "${APP_PATH}")"
BACKEND="${APP_PATH}/Contents/Resources/binaries/qwenpaw-backend/qwenpaw-backend"

if [[ ! -x "${BACKEND}" ]]; then
    echo "ERROR: backend sidecar not executable: ${BACKEND}"
    exit 1
fi

BACKEND_DIR="$(dirname "${BACKEND}")"
BACKEND_NAME="$(basename "${BACKEND}")"
TMP_DIR="$(mktemp -d)"

cleanup() {
    if [[ -n "${BACKEND_PID:-}" ]] && kill -0 "${BACKEND_PID}" 2>/dev/null; then
        kill "${BACKEND_PID}" 2>/dev/null || true
        wait "${BACKEND_PID}" 2>/dev/null || true
    fi
    rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

print_backend_log() {
    echo ""
    echo "== backend stdout/stderr (${LOG_FILE}) =="
    if [[ -f "${LOG_FILE}" ]]; then
        tail -n 300 "${LOG_FILE}" || true
    else
        echo "Log file does not exist"
    fi
    echo ""
    echo "== backend Python log (${PYTHON_LOG_FILE}) =="
    if [[ -f "${PYTHON_LOG_FILE}" ]]; then
        tail -n 300 "${PYTHON_LOG_FILE}" || true
    else
        echo "Python log file does not exist"
    fi
}

ensure_backend_alive() {
    local context="$1"
    if ! kill -0 "${BACKEND_PID}" 2>/dev/null; then
        echo "ERROR: backend exited ${context}"
        print_backend_log
        exit 1
    fi
}

request_ok() {
    local label="$1"
    local path="$2"
    local body_file="${TMP_DIR}/${label//[^A-Za-z0-9_]/_}.body"
    local http_code

    echo "Probe ${label}: ${path}"
    ensure_backend_alive "before ${label}"
    http_code="$(
        curl -sS \
            -H "Origin: http://tauri.localhost" \
            -H "Sec-Fetch-Site: cross-site" \
            -o "${body_file}" \
            -w "%{http_code}" \
            "http://127.0.0.1:${PORT}${path}"
    )"
    ensure_backend_alive "after ${label}"

    if [[ ! "${http_code}" =~ ^2 ]]; then
        echo "ERROR: ${label} returned HTTP ${http_code}"
        echo "response:"
        cat "${body_file}" || true
        print_backend_log
        exit 1
    fi
}

echo "== macOS app signature verification =="
codesign --verify --deep --strict --verbose=2 "${APP_PATH}"
codesign --verify --verbose=2 "${BACKEND}"

echo ""
echo "== backend sidecar smoke test =="
rm -f "${LOG_FILE}" "${PYTHON_LOG_FILE}"
(
    export QWENPAW_DESKTOP_APP=1
    export QWENPAW_DESKTOP_PORT="${PORT}"
    export QWENPAW_TAURI_BACKEND_LOG="${PYTHON_LOG_FILE}"
    export PYTHONUTF8=1
    export PYTHONIOENCODING=utf-8
    export PYTHONUNBUFFERED=1
    export PYTHONFAULTHANDLER=1
    cd "${BACKEND_DIR}"
    exec "./${BACKEND_NAME}"
) >"${LOG_FILE}" 2>&1 &
BACKEND_PID=$!
echo "Started backend pid=${BACKEND_PID} port=${PORT}"

ready=0
for _ in $(seq 1 120); do
    ensure_backend_alive "before readiness"
    if curl -fsS "http://127.0.0.1:${PORT}/api/version" >"${TMP_DIR}/version.json"; then
        ready=1
        break
    fi
    sleep 1
done

if [[ "${ready}" != "1" ]]; then
    echo "ERROR: backend did not become ready"
    print_backend_log
    exit 1
fi

cat "${TMP_DIR}/version.json"
echo ""

request_ok "audio mode" "/api/workspace/audio-mode"
request_ok "transcription provider type" "/api/workspace/transcription-provider-type"
request_ok "transcription providers" "/api/workspace/transcription-providers"
request_ok "local whisper status" "/api/workspace/local-whisper-status"

echo "macOS Tauri app smoke test passed"
