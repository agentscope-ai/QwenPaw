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

# Step 1: Build PyInstaller backend
echo "== Step 1: Building PyInstaller Backend =="
bash scripts/pack-tauri/build_pyinstaller.sh

if [ $? -ne 0 ]; then
    echo "ERROR: PyInstaller rebuild failed"
    exit 1
fi
echo "PyInstaller backend built"
echo ""

# Step 2: Build Tauri app
echo "== Step 2: Building Tauri App =="
cd console

bun install
if [ $? -ne 0 ]; then
    echo "ERROR: bun install failed"
    exit 1
fi

echo "Building for macOS..."
bun tauri build

if [ $? -ne 0 ]; then
    echo "ERROR: Tauri build failed"
    exit 1
fi

cd ..
echo "Tauri app built"
echo ""

echo ""
echo "========================================="
echo "Build Complete!"
echo "========================================="
echo "App: console/src-tauri/target/release/bundle/macos/qwenpaw-console.app"
echo ""
echo "Test: open console/src-tauri/target/release/bundle/macos/qwenpaw-console.app"
echo ""
