#!/usr/bin/env bash
# Build QwenPaw with Tauri for macOS using a conda-packed Python backend env.
#
# Windows and macOS Tauri packages share the same backend resource layout:
# binaries/qwenpaw-backend/env. The Rust shell starts Python from that env.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

VERSION="$(sed -n 's/^__version__[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' src/qwenpaw/__version__.py)"
DIST="${DIST:-dist}"
if [[ "${DIST}" = /* ]]; then
    DIST_ROOT="${DIST}"
else
    DIST_ROOT="${REPO_ROOT}/${DIST}"
fi

ARCHIVE="${DIST_ROOT}/qwenpaw-tauri-backend-env.tar.gz"
BACKEND_RESOURCE="${REPO_ROOT}/console/src-tauri/binaries/qwenpaw-backend"
ENTITLEMENTS_FILE="${REPO_ROOT}/console/src-tauri/entitlements.plist"
SIGN_MACOS_BUNDLE="${REPO_ROOT}/scripts/pack-tauri/sign_macos_bundle.sh"

echo "========================================="
echo "QwenPaw Tauri Build - macOS (conda env backend)"
echo "========================================="
echo "Version: ${VERSION}"
echo ""

echo "== Step 0: Checking prerequisites =="
missing=()
for tool in npm rustc conda; do
    if command -v "${tool}" >/dev/null 2>&1; then
        echo "  [OK] ${tool} ($("${tool}" --version | head -1))"
    else
        echo "  [MISSING] ${tool}"
        missing+=("${tool}")
    fi
done
if [[ ${#missing[@]} -gt 0 ]]; then
    echo "Missing prerequisites: ${missing[*]}"
    exit 1
fi
if [[ ! -f "${ENTITLEMENTS_FILE}" ]]; then
    echo "ERROR: macOS entitlements file not found at ${ENTITLEMENTS_FILE}"
    exit 1
fi
if [[ ! -f "${SIGN_MACOS_BUNDLE}" ]]; then
    echo "ERROR: macOS signing helper not found at ${SIGN_MACOS_BUNDLE}"
    exit 1
fi
echo ""

if [[ -z "${APPLE_SIGNING_IDENTITY:-}" && -z "${APPLE_CERTIFICATE:-}" ]]; then
    export APPLE_SIGNING_IDENTITY="-"
    echo "Using ad-hoc macOS code signing"
fi
echo ""

echo "== Step 1: Building backend Python env =="
mkdir -p "${DIST_ROOT}"
bash scripts/wheel_build.sh
python scripts/pack/build_common.py --output "${ARCHIVE}" --format tar.gz
python scripts/pack-tauri/stage_backend_env.py \
    --archive "${ARCHIVE}" \
    --resource-dir "${BACKEND_RESOURCE}"
echo "Tauri backend resource ready: ${BACKEND_RESOURCE}"
echo ""

echo "== Step 2: Building Tauri app =="
BUNDLE_DIR="${REPO_ROOT}/console/src-tauri/target/release/bundle"
rm -rf "${BUNDLE_DIR}/dmg" "${BUNDLE_DIR}/macos"
(
    cd console
    npm ci
    npm run sync:tauri-version
    npm exec -- tauri build \
        --config src-tauri/tauri.version.conf.json \
        --bundles app
)
echo "Tauri app built"
echo ""

APP_PATH="${BUNDLE_DIR}/macos/QwenPaw Desktop.app"
if [[ ! -d "${APP_PATH}" ]]; then
    echo "ERROR: No Tauri macOS app found at ${APP_PATH}"
    exit 1
fi

echo "== Step 3: Signing final macOS app =="
bash "${SIGN_MACOS_BUNDLE}" \
    "${APP_PATH}" \
    "${APPLE_SIGNING_IDENTITY}" \
    "${ENTITLEMENTS_FILE}"
echo "Final macOS app signed and verified"
echo ""

echo "== Step 4: Collecting distribution artifacts =="
DIST_DIR="${DIST_ROOT}/tauri-macos"
rm -rf "${DIST_DIR}"
mkdir -p "${DIST_DIR}"
cp -R "${APP_PATH}" "${DIST_DIR}/"
STAGED_APP_PATH="${DIST_DIR}/$(basename "${APP_PATH}")"
echo ".app copied to ${STAGED_APP_PATH}"

ZIP_NAME="${DIST_ROOT}/QwenPaw-Tauri-${VERSION}-macOS.zip"
rm -f "${ZIP_NAME}"
if command -v ditto >/dev/null 2>&1; then
    ditto -c -k --sequesterRsrc --keepParent "${STAGED_APP_PATH}" "${ZIP_NAME}"
else
    (
        cd "${DIST_DIR}"
        zip -r "${ZIP_NAME}" "$(basename "${STAGED_APP_PATH}")"
    )
fi

if [[ ! -f "${ZIP_NAME}" ]]; then
    echo "ERROR: Failed to create ZIP archive"
    exit 1
fi
SIZE="$(du -sh "${ZIP_NAME}" | cut -f1)"
echo "Created ${ZIP_NAME} (${SIZE})"
echo ""

echo "========================================="
echo "Build Complete!"
echo "========================================="
echo "App:          ${APP_PATH}"
echo "Distribution: ${DIST_DIR}"
echo "Archive:      ${ZIP_NAME}"
echo ""
