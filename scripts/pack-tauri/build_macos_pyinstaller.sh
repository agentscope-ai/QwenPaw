#!/usr/bin/env bash
# Build QwenPaw with Tauri for macOS (PyInstaller backend)
# Creates a self-contained desktop app with bundled Python backend
#
# Usage:
#   ./scripts/pack-tauri/build_macos_pyinstaller.sh

set -e

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

DIST="${DIST:-dist}"
VERSION=$(sed -n 's/^__version__[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' src/qwenpaw/__version__.py)

echo "========================================="
echo "QwenPaw Tauri Build - macOS (PyInstaller)"
echo "========================================="
echo "Version: ${VERSION}"
echo ""

# Step 0: Prerequisites
echo "== Step 0: Checking Prerequisites =="
missing=()

if command -v bun &>/dev/null; then
    echo "  [OK] bun ($(bun --version))"
else
    echo "  [MISSING] bun"
    echo "    Install: https://bun.sh"
    missing+=("bun")
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

# Step 1: Build console frontend
echo "== Step 1: Building Console Frontend =="
cd console

# if [ ! -d "node_modules" ]; then
#     echo "Installing frontend dependencies..."
    bun install
# fi

echo "Building frontend..."
bun build:prod

if [ $? -ne 0 ]; then
    echo "ERROR: Frontend build failed"
    exit 1
fi
cd ..
# cp -R console/dist/. src/qwenpaw/console/
# echo ""

# Step 2: Build PyInstaller backend with embedded frontend
echo "== Step 2: Building PyInstaller Backend with embedded frontend =="
bash scripts/pack-tauri/build_pyinstaller.sh

if [ $? -ne 0 ]; then
    echo "ERROR: PyInstaller rebuild failed"
    exit 1
fi
echo "PyInstaller backend built with frontend"
echo ""

# Step 3: Build Tauri app
echo "== Step 3: Building Tauri App =="
cd console

echo "Building for macOS..."
bun tauri build

if [ $? -ne 0 ]; then
    echo "ERROR: Tauri build failed"
    exit 1
fi

cd ..
echo "Tauri app built"
echo ""

# Step 4: Create distribution
echo "== Step 4: Creating Distribution =="

BUILT_APP="console/src-tauri/target/release/bundle/macos/qwenpaw-console.app"
if [ ! -d "${BUILT_APP}" ]; then
    echo "WARNING: ${BUILT_APP} not found, searching alternatives..."
    BUILT_APP=$(find console/src-tauri/target/release/bundle -name "*.app" -maxdepth 2 2>/dev/null | head -1)
fi

# DMG bundling cleans up the .app — extract from DMG if needed
if [ -z "${BUILT_APP}" ] || [ ! -d "${BUILT_APP}" ]; then
    BUILT_DMG=$(find console/src-tauri/target/release/bundle/dmg -name "*.dmg" -maxdepth 1 2>/dev/null | head -1)
    if [ -n "${BUILT_DMG}" ]; then
        echo "Extracting .app from ${BUILT_DMG}..."
        MOUNT_DIR=$(mktemp -d)
        hdiutil attach "${BUILT_DMG}" -mountpoint "${MOUNT_DIR}" -quiet
        BUILT_APP=$(find "${MOUNT_DIR}" -name "*.app" -maxdepth 1 | head -1)
        if [ -z "${BUILT_APP}" ]; then
            hdiutil detach "${MOUNT_DIR}" -quiet
            echo "ERROR: No .app found inside DMG"
            exit 1
        fi
        # Copy .app out before unmounting
        EXTRACTED_APP="console/src-tauri/target/release/bundle/macos/$(basename "${BUILT_APP}")"
        mkdir -p "$(dirname "${EXTRACTED_APP}")"
        cp -R "${BUILT_APP}" "${EXTRACTED_APP}"
        hdiutil detach "${MOUNT_DIR}" -quiet
        BUILT_APP="${EXTRACTED_APP}"
    else
        echo "ERROR: Built app not found (no .app or .dmg)"
        exit 1
    fi
fi

echo "Found app: ${BUILT_APP}"

mkdir -p "${DIST}/tauri-macos"
rm -rf "${DIST}/tauri-macos/QwenPaw.app"
cp -R "${BUILT_APP}" "${DIST}/tauri-macos/QwenPaw.app"
codesign --force --deep --sign - "${DIST}/tauri-macos/QwenPaw.app" 2>/dev/null || true

ZIP_NAME="${DIST}/QwenPaw-Tauri-${VERSION}-macOS.zip"
if [ -f "${ZIP_NAME}" ]; then
    rm "${ZIP_NAME}"
fi

ditto -c -k --sequesterRsrc --keepParent "${DIST}/tauri-macos/QwenPaw.app" "${ZIP_NAME}"

if [ $? -eq 0 ]; then
    SIZE=$(du -h "${ZIP_NAME}" | cut -f1)
    echo "Created ${ZIP_NAME} (${SIZE})"
else
    echo "ERROR: Failed to create distribution"
    exit 1
fi

echo ""
echo "========================================="
echo "Build Complete!"
echo "========================================="
echo "App: ${DIST}/tauri-macos/QwenPaw.app"
echo "Distribution: ${ZIP_NAME}"
echo ""
echo "Test: open ${DIST}/tauri-macos/QwenPaw.app"
echo ""
