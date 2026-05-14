#!/usr/bin/env bash
# Build QwenPaw with Tauri for macOS (PyInstaller backend)
# Creates a self-contained desktop app with bundled Python backend
#
# Usage:
#   ./scripts/pack-tauri/build_macos_pyinstaller.sh

set -e

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

VERSION=$(sed -n 's/^__version__[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' src/qwenpaw/__version__.py)

echo "========================================="
echo "QwenPaw Tauri Build - macOS (PyInstaller)"
echo "========================================="
echo "Version: ${VERSION}"
echo ""

# Step 0: Prerequisites
echo "== Step 0: Checking Prerequisites =="
missing=()

if command -v npm &>/dev/null; then
    echo "  [OK] npm ($(npm --version))"
else
    echo "  [MISSING] npm"
    echo "    Install Node.js: https://nodejs.org/"
    missing+=("npm")
fi

if command -v rustc &>/dev/null; then
    echo "  [OK] rustc ($(rustc --version))"
else
    echo "  [MISSING] rustc (Rust)"
    echo "    Install: https://rustup.rs"
    missing+=("rustc")
fi

if command -v uv &>/dev/null; then
    echo "  [OK] uv ($(uv --version))"
else
    echo "  [MISSING] uv"
    echo "    Install: https://docs.astral.sh/uv/getting-started/installation/"
    missing+=("uv")
fi

if [ ${#missing[@]} -gt 0 ]; then
    echo ""
    echo "Missing prerequisites: ${missing[*]}"
    echo "Install the missing tools and re-run this script."
    exit 1
fi
echo ""

# Step 1: Build PyInstaller backend
echo "== Step 1: Building PyInstaller Backend =="
bash scripts/pack-tauri/build_pyinstaller.sh
echo "PyInstaller backend built"
echo ""

# Step 2: Build Tauri app
echo "== Step 2: Building Tauri App =="
BUNDLE_DIR="${REPO_ROOT}/console/src-tauri/target/release/bundle"
rm -rf "${BUNDLE_DIR}/dmg" "${BUNDLE_DIR}/macos"
cd console
npm ci
echo "Syncing Tauri version..."
npm run sync:tauri-version
echo "Building for macOS..."
if [ -z "${APPLE_SIGNING_IDENTITY:-}" ] && [ -z "${APPLE_CERTIFICATE:-}" ]; then
    # The Tauri app and PyInstaller sidecar are native Mach-O executables.
    # Keep their signature state consistent when no Developer ID certificate is
    # configured; notarization is still required for fully trusted distribution.
    export APPLE_SIGNING_IDENTITY="-"
    echo "Using ad-hoc macOS code signing"
fi
npm exec -- tauri build --config src-tauri/tauri.version.conf.json
cd ..
echo "Tauri app built"
echo ""

# Step 3: Collect distribution artifacts
echo "== Step 3: Collecting Distribution Artifacts =="
DIST="${DIST:-dist}"
if [[ "${DIST}" = /* ]]; then
    DIST_ROOT="${DIST}"
else
    DIST_ROOT="${REPO_ROOT}/${DIST}"
fi
DIST_DIR="${DIST_ROOT}/tauri-macos"
rm -rf "${DIST_DIR}"
mkdir -p "${DIST_DIR}"

# Match the legacy macOS package shape: one zip containing one .app bundle.
# The DMG remains in Tauri's build output for local debugging, but shipping
# both doubles the public artifact size and changes the user-facing layout.
APP_PATH="${BUNDLE_DIR}/macos/QwenPaw Desktop.app"
if [ ! -d "${APP_PATH}" ]; then
    echo "ERROR: No Tauri macOS app found at ${APP_PATH}"
    exit 1
fi

cp -R "${APP_PATH}" "${DIST_DIR}/"
echo ".app copied to ${DIST_DIR}/"

# Create ZIP archive
ZIP_NAME="${DIST_ROOT}/QwenPaw-Tauri-${VERSION}-macOS.zip"
if [ -f "${ZIP_NAME}" ]; then
    rm -f "${ZIP_NAME}"
fi
if command -v ditto &>/dev/null; then
    ditto -c -k --sequesterRsrc --keepParent "${APP_PATH}" "${ZIP_NAME}"
else
    cd "${DIST_DIR}"
    zip -r "${ZIP_NAME}" "QwenPaw Desktop.app"
    cd "${REPO_ROOT}"
fi

if [ -f "${ZIP_NAME}" ]; then
    SIZE=$(du -sh "${ZIP_NAME}" | cut -f1)
    echo "Created ${ZIP_NAME} (${SIZE})"
else
    echo "ERROR: Failed to create ZIP archive"
    exit 1
fi
echo ""

echo ""
echo "========================================="
echo "Build Complete!"
echo "========================================="
echo "App:          ${APP_PATH}"
echo "Distribution: ${DIST_DIR}"
echo "Archive:      ${ZIP_NAME}"
echo ""
echo "Test: open \"${APP_PATH}\""
echo ""
