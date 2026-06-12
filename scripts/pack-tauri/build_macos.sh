#!/usr/bin/env bash
# Build QwenPaw with Tauri for macOS (conda-pack backend).
#
# Usage:
#   ./scripts/pack-tauri/build_macos.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

VERSION="$(
  sed -n 's/^__version__[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' \
    src/qwenpaw/__version__.py
)"
SIGN_MACOS_BUNDLE="${REPO_ROOT}/scripts/pack-tauri/sign_macos_bundle.sh"

echo "========================================="
echo "QwenPaw Tauri Build - macOS (conda-pack)"
echo "========================================="
echo "Version: ${VERSION}"
echo ""

echo "== Step 0: Checking Prerequisites =="
missing=()
for tool in npm rustc; do
  if command -v "$tool" >/dev/null 2>&1; then
    echo "  [OK] ${tool}"
  else
    echo "  [MISSING] ${tool}"
    missing+=("$tool")
  fi
done
if command -v conda >/dev/null 2>&1 || [[ -n "${CONDA_EXE:-}" ]]; then
  echo "  [OK] conda"
else
  echo "  [MISSING] conda"
  missing+=("conda")
fi
if [[ ${#missing[@]} -gt 0 ]]; then
  echo ""
  echo "Missing prerequisites: ${missing[*]}"
  exit 1
fi
if [[ ! -f "${SIGN_MACOS_BUNDLE}" ]]; then
  echo "ERROR: macOS signing helper not found at ${SIGN_MACOS_BUNDLE}" >&2
  exit 1
fi

if [[ -z "${APPLE_SIGNING_IDENTITY:-}" && -z "${APPLE_CERTIFICATE:-}" ]]; then
  export APPLE_SIGNING_IDENTITY="-"
  echo "Using ad-hoc macOS code signing"
fi
echo ""

echo "== Step 1: Building Console Static Assets =="
cd console
npm ci
echo "Generating Tauri icons..."
npm exec -- tauri icon ../scripts/pack/assets/icon.svg
echo "Syncing Tauri version..."
node ../scripts/pack-tauri/sync_tauri_version.mjs
echo "Building console frontend..."
npm run build:prod
cd ..
echo "Console static assets built"
echo ""

echo "== Step 2: Building conda-packed backend =="
bash scripts/pack-tauri/build_conda_env.sh
echo "conda-packed backend built"
echo ""

echo "== Step 2b: Signing backend native files =="
bash "${SIGN_MACOS_BUNDLE}" \
  "${REPO_ROOT}/console/src-tauri/binaries/qwenpaw-backend" \
  "${APPLE_SIGNING_IDENTITY}"
echo "Backend native files signed"
echo ""

echo "== Step 3: Building Tauri App =="
BUNDLE_DIR="${REPO_ROOT}/console/src-tauri/target/release/bundle"
rm -rf "${BUNDLE_DIR}/dmg" "${BUNDLE_DIR}/macos"
cd console
npm exec -- tauri build \
  --config src-tauri/tauri.version.conf.json \
  --bundles app
cd ..
echo "Tauri app built"
echo ""

APP_PATH="${BUNDLE_DIR}/macos/QwenPaw Desktop.app"
if [[ ! -d "${APP_PATH}" ]]; then
  echo "ERROR: No Tauri macOS app found at ${APP_PATH}" >&2
  exit 1
fi

echo "== Step 3b: Signing Final macOS App =="
bash "${SIGN_MACOS_BUNDLE}" \
  "${APP_PATH}" \
  "${APPLE_SIGNING_IDENTITY}"
echo "Final macOS app signed and verified"
echo ""

echo "== Step 4: Collecting Distribution Artifacts =="
DIST="${DIST:-dist}"
if [[ "$DIST" != /* ]]; then
  DIST_ROOT="${REPO_ROOT}/${DIST}"
else
  DIST_ROOT="$DIST"
fi
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
  (cd "${DIST_DIR}" && zip -r "${ZIP_NAME}" "$(basename "${STAGED_APP_PATH}")")
fi

if [[ -f "${ZIP_NAME}" ]]; then
  SIZE="$(du -sh "${ZIP_NAME}" | cut -f1)"
  echo "Created ${ZIP_NAME} (${SIZE})"
else
  echo "ERROR: Failed to create ZIP archive" >&2
  exit 1
fi

echo ""
echo "========================================="
echo "Build Complete!"
echo "========================================="
echo "App:          ${APP_PATH}"
echo "Distribution: ${DIST_DIR}"
echo "Archive:      ${ZIP_NAME}"
