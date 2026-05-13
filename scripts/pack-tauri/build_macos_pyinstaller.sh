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
cd console
npm ci
echo "Syncing Tauri version..."
npm run sync:tauri-version
echo "Building for macOS..."
npm exec -- tauri build
cd ..
echo "Tauri app built"
echo ""

# Step 3: Collect distribution artifacts
echo "== Step 3: Collecting Distribution Artifacts =="
DIST="${DIST:-dist}"
DIST_DIR="${REPO_ROOT}/${DIST}/tauri-macos"
BUNDLE_DIR="${REPO_ROOT}/console/src-tauri/target/release/bundle"
mkdir -p "${DIST_DIR}"

# Copy DMG if present
if ls "${BUNDLE_DIR}/dmg/"*.dmg &>/dev/null; then
    cp "${BUNDLE_DIR}/dmg/"*.dmg "${DIST_DIR}/"
    echo "DMG copied to ${DIST_DIR}/"
fi

# Copy .app if present
APP_PATH="${BUNDLE_DIR}/macos/QwenPaw Desktop.app"
if [ -d "${APP_PATH}" ]; then
    cp -R "${APP_PATH}" "${DIST_DIR}/"
    echo ".app copied to ${DIST_DIR}/"
fi

# Create ZIP archive
ZIP_NAME="${REPO_ROOT}/${DIST}/QwenPaw-Tauri-${VERSION}-macOS.zip"
if [ -f "${ZIP_NAME}" ]; then
    rm -f "${ZIP_NAME}"
fi
cd "${DIST_DIR}"
zip -r "${ZIP_NAME}" .
cd "${REPO_ROOT}"

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
echo "App:          console/src-tauri/target/release/bundle/macos/QwenPaw Desktop.app"
echo "Distribution: ${DIST_DIR}"
echo "Archive:      ${ZIP_NAME}"
echo ""
echo "Test: open \"${APP_PATH}\""
echo ""
