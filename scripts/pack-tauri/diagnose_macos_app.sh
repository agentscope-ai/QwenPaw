#!/usr/bin/env bash
# Diagnose the packaged macOS Tauri app without launching the GUI.
#
# The check verifies the app signature, validates the packaged conda env
# backend, then starts Python and probes the endpoints used by the desktop
# settings and voice transcription pages.

set -euo pipefail

APP_PATH="${1:?Usage: diagnose_macos_app.sh <QwenPaw Desktop.app>}"
PORT="${QWENPAW_DIAG_PORT:-19088}"
LOG_FILE="${QWENPAW_DIAG_LOG:-tauri-backend-smoke.log}"
if [[ "${LOG_FILE}" != /* ]]; then
    LOG_FILE="$(pwd)/${LOG_FILE}"
fi
SIDECAR_LOG_FILE="${QWENPAW_DIAG_SIDECAR_LOG:-${LOG_FILE}.python.log}"

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

BACKEND_DIR="${APP_PATH}/Contents/Resources/binaries/qwenpaw-backend"
PYTHON="${BACKEND_DIR}/env/bin/python"

if [[ ! -x "${PYTHON}" ]]; then
    echo "ERROR: packaged Python not executable: ${PYTHON}"
    exit 1
fi

is_macho() {
    file -b "$1" | grep -q "Mach-O"
}

is_inside_framework() {
    [[ "$1" == *".framework/"* ]]
}

echo "== macOS app signature verification =="
codesign --verify --deep --strict --verbose=4 "${APP_PATH}"
codesign -dv --verbose=4 "${APP_PATH}" 2>&1 || true

echo ""
echo "== packaged Python env diagnostics =="
(
    export PYTHONNOUSERSITE=1
    export PATH="${BACKEND_DIR}/env/bin:${PATH}"
    "${PYTHON}" - <<'PY'
import importlib.util
import sys

import certifi

print(f"python={sys.executable}")
print(f"prefix={sys.prefix}")
print(f"base_prefix={sys.base_prefix}")
print(f"certifi={certifi.where()}")
print(f"whisper_present={importlib.util.find_spec('whisper') is not None}")
print(f"torch_present={importlib.util.find_spec('torch') is not None}")

import whisper  # noqa: F401

print("whisper_import=ok")
PY
)

echo ""
echo "== bundled Mach-O signature scan =="
checked=0
skipped_framework_members=0
while IFS= read -r -d '' path; do
    if is_inside_framework "${path}"; then
        skipped_framework_members=$((skipped_framework_members + 1))
        continue
    fi
    if is_macho "${path}"; then
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
echo "== backend smoke test =="
rm -f "${LOG_FILE}"
rm -f "${SIDECAR_LOG_FILE}"
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
echo "== backend process log (${LOG_FILE}) =="
    if [[ -f "${LOG_FILE}" ]]; then
        tail -n 300 "${LOG_FILE}" || true
    else
        echo "Log file does not exist"
    fi
    echo ""
    echo "== python backend diagnostics (${SIDECAR_LOG_FILE}) =="
    if [[ -f "${SIDECAR_LOG_FILE}" ]]; then
        tail -n 300 "${SIDECAR_LOG_FILE}" || true
    else
        echo "Python backend diagnostics file does not exist"
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

probe_voice_page_concurrent() {
    local rounds="${1:-5}"
    local endpoints=(
        "audio_mode:/api/workspace/audio-mode"
        "transcription_provider_type:/api/workspace/transcription-provider-type"
        "transcription_providers:/api/workspace/transcription-providers"
        "local_whisper_status:/api/workspace/local-whisper-status"
    )

    echo ""
    echo "== concurrent voice transcription settings probe =="
    for round in $(seq 1 "${rounds}"); do
        echo "-- round ${round}/${rounds}"
        ensure_backend_alive "before concurrent voice round ${round}"

        local pids=()
        local labels=()
        local failed=0
        local idx=0
        local item
        for item in "${endpoints[@]}"; do
            local label="${item%%:*}"
            local path="${item#*:}"
            local body_file="${TMP_DIR}/concurrent_${round}_${label}.body"
            local meta_file="${TMP_DIR}/concurrent_${round}_${label}.meta"
            labels[idx]="${label}"
            (
                curl -sS \
                    -H "Origin: http://tauri.localhost" \
                    -H "Sec-Fetch-Site: cross-site" \
                    -o "${body_file}" \
                    -w "http_code=%{http_code}\n" \
                    "http://127.0.0.1:${PORT}${path}" > "${meta_file}"
            ) &
            pids[idx]=$!
            idx=$((idx + 1))
        done

        for idx in "${!pids[@]}"; do
            local label="${labels[idx]}"
            local body_file="${TMP_DIR}/concurrent_${round}_${label}.body"
            local meta_file="${TMP_DIR}/concurrent_${round}_${label}.meta"
            if ! wait "${pids[idx]}"; then
                failed=1
            fi

            echo "concurrent ${label}:"
            cat "${meta_file}" || true
            echo "response:"
            cat "${body_file}" || true
            echo ""

            local http_code
            http_code="$(sed -n 's/^http_code=//p' "${meta_file}" | tail -1)"
            if [[ ! "${http_code}" =~ ^2 ]]; then
                failed=1
            fi
        done

        sleep 1
        ensure_backend_alive "after concurrent voice round ${round}"
        if [[ "${failed}" != "0" ]]; then
            echo "ERROR: concurrent voice round ${round} failed"
            print_backend_log
            exit 1
        fi
    done
}

(
    export QWENPAW_DESKTOP_APP=1
    export QWENPAW_DESKTOP_PORT="${PORT}"
    export QWENPAW_TAURI_BACKEND_LOG="${SIDECAR_LOG_FILE}"
    export QWENPAW_LOG_LEVEL="${QWENPAW_LOG_LEVEL:-debug}"
    export PYTHONUTF8=1
    export PYTHONIOENCODING=utf-8
    export PYTHONUNBUFFERED=1
    export PYTHONFAULTHANDLER=1
    cd "${BACKEND_DIR}"
    exec "${PYTHON}" -u -m qwenpaw.tauri.entry
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
probe_voice_page_concurrent 5

echo "Backend diagnostics passed"
