#!/usr/bin/env bash
# Create a compressed DMG from the built .app bundle.
# Usage: bash scripts/pack-tauri/build_dmg_macos.sh
# Requires: hdiutil (built-in macOS tool, no extra install needed)
# Run from repo root after build_macos_pyinstaller.sh has completed.

set -e
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

DIST="dist/tauri-macos"
APP_NAME="QwenPaw"
APP_DIR="${DIST}/${APP_NAME}.app"

# --- Version ---
VERSION_FILE="${REPO_ROOT}/src/qwenpaw/__version__.py"
VERSION=""
if [[ -f "${VERSION_FILE}" ]]; then
  VERSION="$(
    sed -n 's/^__version__[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' \
      "${VERSION_FILE}" 2>/dev/null
  )"
fi
if [[ -z "${VERSION}" ]]; then
  VERSION="0.0.0"
  echo "Warning: could not read version from __version__.py, using ${VERSION}"
fi

DMG_NAME="${DIST}/${APP_NAME}-${VERSION}-macOS.dmg"
STAGING="$(mktemp -d)/dmg-staging"

# --- Pre-flight checks ---
if [[ ! -d "${APP_DIR}" ]]; then
  echo "Error: ${APP_DIR} not found. Run build_macos_pyinstaller.sh first."
  exit 1
fi

echo "== Building DMG =="
echo "   App    : ${APP_DIR}"
echo "   Output : ${DMG_NAME}"
echo "   Version: ${VERSION}"
echo ""

# --- Staging ---
echo "== Preparing staging area =="
mkdir -p "${STAGING}"

# ditto preserves hard links (critical for conda envs) and macOS metadata
ditto "${APP_DIR}" "${STAGING}/${APP_NAME}.app"

# Add /Applications symlink so users can drag-and-drop to install
ln -s /Applications "${STAGING}/Applications"

# --- Create DMG ---
echo "== Creating compressed DMG =="
rm -f "${DMG_NAME}"

hdiutil create \
  -volname "${APP_NAME}" \
  -srcfolder "${STAGING}" \
  -ov \
  -format UDZO \
  -imagekey zlib-level=9 \
  "${DMG_NAME}"

# --- Cleanup ---
rm -rf "$(dirname "${STAGING}")"

# --- Result ---
DMG_SIZE="$(du -sh "${DMG_NAME}" | cut -f1)"
echo ""
echo "== Done =="
echo "   ${DMG_NAME} (${DMG_SIZE})"
