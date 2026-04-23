#!/usr/bin/env bash
# Build QwenPaw backend with PyInstaller for Tauri sidecar
# Creates a standalone onefile executable with embedded Python runtime
#
# Usage:
#   ./scripts/pack-tauri/build_pyinstaller.sh
#
# Prerequisites:
#   - Python 3.10+ with virtual environment
#   - PyInstaller 6.0+ (will be installed if not present)

set -e

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

DIST="${DIST:-dist}"
VERSION=$(sed -n 's/^__version__[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' src/qwenpaw/__version__.py)

echo "========================================="
echo "QwenPaw PyInstaller Build"
echo "========================================="
echo "Version: ${VERSION}"
echo "Repository: ${REPO_ROOT}"
echo ""

# Check prerequisites
echo "== Checking prerequisites =="

# Create venv if missing (prefer uv if available)
PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
if [ ! -f "$PYTHON_BIN" ]; then
    if command -v uv &>/dev/null; then
        echo "Creating virtual environment with uv..."
        uv venv "${REPO_ROOT}/.venv"
    else
        echo "ERROR: Python not found in .venv"
        echo "Please create virtual environment first: python -m venv .venv"
        exit 1
    fi
fi

echo "Python: $("$PYTHON_BIN" --version)"

# Install PyInstaller if not present
echo "== Installing PyInstaller =="
if ! "$PYTHON_BIN" -c "import PyInstaller" 2> /dev/null; then
    echo "Installing PyInstaller..."
    if command -v uv &>/dev/null; then
        uv pip install "pyinstaller>=6.0.0"
    else
        "$PYTHON_BIN" -m pip install "pyinstaller>=6.0.0"
    fi
fi
echo "PyInstaller installed"
echo ""

# Run PyInstaller
echo "== Running PyInstaller =="
echo "Building standalone executable..."

SPEC_FILE="${REPO_ROOT}/scripts/pack-tauri/qwenpaw.spec"
if [ ! -f "$SPEC_FILE" ]; then
    echo "ERROR: Spec file not found at ${SPEC_FILE}"
    exit 1
fi

"$PYTHON_BIN" -m PyInstaller "$SPEC_FILE" \
    --distpath "${DIST}/pyinstaller" \
    --workpath "${DIST}/pyinstaller-build" \
    --clean \
    --noconfirm

if [ $? -ne 0 ]; then
    echo "ERROR: PyInstaller build failed"
    exit 1
fi

echo "PyInstaller build complete"
echo ""

# Verify output
BACKEND_EXE="${DIST}/pyinstaller/qwenpaw-backend"
if [ ! -f "${BACKEND_EXE}" ]; then
    echo "ERROR: Backend executable not found at ${BACKEND_EXE}"
    exit 1
fi

echo "Backend executable created: ${BACKEND_EXE}"

# Get size
SIZE=$(du -sh "${BACKEND_EXE}" | cut -f1)
echo "Bundle size: ${SIZE}"
echo ""

# Copy to Tauri binaries directory with target triple suffix
echo "== Copying to Tauri binaries directory =="
TARGET_TRIPLE=$(rustc --print host-tuple 2>/dev/null || echo "unknown")
BINARIES_DIR="${REPO_ROOT}/console/src-tauri/binaries"
mkdir -p "${BINARIES_DIR}"

DEST="${BINARIES_DIR}/qwenpaw-backend-${TARGET_TRIPLE}"
cp "${BACKEND_EXE}" "${DEST}"
chmod +x "${DEST}"
echo "Copied to: ${DEST}"
echo ""

echo "========================================="
echo "PyInstaller Build Complete!"
echo "========================================="
echo "Output:"
echo "  Executable: ${BACKEND_EXE}"
echo "  Tauri sidecar: ${DEST}"
echo ""
