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

if [ $? -ne 0 ]; then
    echo "ERROR: PyInstaller build failed"
    exit 1
fi
echo "PyInstaller backend ready"
echo ""

# Step 2: Build console frontend and copy to Python package
echo "== Step 2: Building Console Frontend =="
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

# Step 3: Rebuild PyInstaller with embedded frontend
echo "== Step 3: Rebuilding PyInstaller with embedded frontend =="
bash scripts/pack-tauri/build_pyinstaller.sh

if [ $? -ne 0 ]; then
    echo "ERROR: PyInstaller rebuild failed"
    exit 1
fi
echo "PyInstaller backend rebuilt with frontend"
echo ""

# Step 4: Build Tauri app
echo "== Step 4: Building Tauri App =="
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

# Step 5: Create distribution
echo "== Step 5: Creating Distribution =="

BUILT_APP="console/src-tauri/target/release/bundle/macos/qwenpaw-console.app"
if [ ! -d "${BUILT_APP}" ]; then
    echo "WARNING: ${BUILT_APP} not found, searching alternatives..."
    BUILT_APP=$(find console/src-tauri/target/release/bundle -name "*.app" -maxdepth 2 2>/dev/null | head -1)
    if [ -z "${BUILT_APP}" ]; then
        echo "ERROR: Built app not found"
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
