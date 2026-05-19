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
APP_PARENT="$(cd "$(dirname "${APP_PATH}")" && pwd)"
APP_PATH="${APP_PARENT}/$(basename "${APP_PATH}")"

BACKEND="${APP_PATH}/Contents/Resources/binaries/qwenpaw-backend/qwenpaw-backend"
if [[ ! -x "${BACKEND}" ]]; then
    echo "ERROR: backend sidecar not executable: ${BACKEND}"
    exit 1
fi
BACKEND_DIR="$(dirname "${BACKEND}")"
BACKEND_NAME="$(basename "${BACKEND}")"

echo "== macOS app signature verification =="
codesign --verify --deep --strict --verbose=4 "${APP_PATH}"
codesign -dv --verbose=4 "${APP_PATH}" 2>&1 || true

echo ""
echo "== backend sidecar signature =="
codesign --verify --verbose=4 "${BACKEND}"
codesign -dv --verbose=4 "${BACKEND}" 2>&1 || true

echo ""
echo "== key Python/native dependency diagnostics =="
while IFS= read -r path; do
    if [[ -z "${path}" ]]; then
        continue
    fi
    echo "-- ${path}"
    file "${path}" || true
    codesign --verify --verbose=2 "${path}" || true
    codesign -dv --verbose=4 "${path}" 2>&1 || true
    if command -v otool >/dev/null 2>&1; then
        otool -L "${path}" || true
    fi
done < <(
    find "${BACKEND_DIR}/_internal" \
        \( -path "*/Python.framework" -o \
           -name "Python" -o \
           -name "libtorch*.dylib" -o \
           -name "libc10*.dylib" -o \
           -name "libshm.dylib" \) \
        2>/dev/null | sort
)

echo ""
echo "== bundled Mach-O signature scan =="
checked=0
skipped_framework_members=0
while IFS= read -r -d '' path; do
    if [[ "${path}" == *".framework/"* ]]; then
        skipped_framework_members=$((skipped_framework_members + 1))
        continue
    fi
    if file -b "${path}" | grep -q "Mach-O"; then
        codesign --verify --verbose=2 "${path}"
        checked=$((checked + 1))
    fi
done < <(find "${APP_PATH}" -type f -print0)
echo "Verified ${checked} bundled Mach-O files"
echo "Skipped ${skipped_framework_members} framework member files"

echo ""
echo "== bundled framework signature scan =="
checked_frameworks=0
while IFS= read -r framework; do
    if [[ -n "${framework}" ]]; then
        codesign --verify --verbose=2 "${framework}"
        checked_frameworks=$((checked_frameworks + 1))
    fi
done < <(find "${APP_PATH}" -type d -name "*.framework" | sort -r)
echo "Verified ${checked_frameworks} bundled frameworks"

echo ""
echo "== backend sidecar smoke test =="
rm -f "${LOG_FILE}"
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
    echo "== backend sidecar log (${LOG_FILE}) =="
    if [[ -f "${LOG_FILE}" ]]; then
        tail -n 300 "${LOG_FILE}" || true
    else
        echo "Log file does not exist"
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

probe_endpoint() {
    local label="$1"
    local path="$2"
    local body_file="${TMP_DIR}/${label//[^A-Za-z0-9_]/_}.body"
    local meta_file="${TMP_DIR}/${label//[^A-Za-z0-9_]/_}.meta"

    echo ""
    echo "== probe: ${label} (${path}) =="
    ensure_backend_alive "before ${label}"
    set +e
    curl -sS \
        -H "Origin: http://tauri.localhost" \
        -H "Sec-Fetch-Site: cross-site" \
        -o "${body_file}" \
        -w "http_code=%{http_code}\n" \
        "http://127.0.0.1:${PORT}${path}" > "${meta_file}"
    local curl_status=$?
    set -e

    cat "${meta_file}"
    echo "response:"
    cat "${body_file}" || true
    echo ""

    sleep 1
    ensure_backend_alive "after ${label}"

    local http_code
    http_code="$(sed -n 's/^http_code=//p' "${meta_file}" | tail -1)"
    if [[ "${curl_status}" != "0" || ! "${http_code}" =~ ^2 ]]; then
        echo "ERROR: ${label} failed (curl=${curl_status}, http=${http_code})"
        print_backend_log
        exit 1
    fi
}

(
    export QWENPAW_DESKTOP_APP=1
    export QWENPAW_DESKTOP_PORT="${PORT}"
    export PYTHONUTF8=1
    export PYTHONIOENCODING=utf-8
    cd "${BACKEND_DIR}"
    "./${BACKEND_NAME}"
) > "${LOG_FILE}" 2>&1 &
BACKEND_PID=$!

echo "Started backend pid=${BACKEND_PID} port=${PORT}"

ready=0
for _ in $(seq 1 120); do
    ensure_backend_alive "before becoming ready"
    if curl -fsS "http://127.0.0.1:${PORT}/api/version" > "${TMP_DIR}/qwenpaw-version.json"; then
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

echo "version:"
cat "${TMP_DIR}/qwenpaw-version.json"
echo ""

probe_endpoint "audio mode" "/api/workspace/audio-mode"
probe_endpoint "transcription provider type" "/api/workspace/transcription-provider-type"
probe_endpoint "transcription providers" "/api/workspace/transcription-providers"
probe_endpoint "local whisper status" "/api/workspace/local-whisper-status"

echo "Backend diagnostics passed"
