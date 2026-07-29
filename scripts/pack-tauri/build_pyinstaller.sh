#!/usr/bin/env bash
# Build QwenPaw backend with PyInstaller for Tauri sidecar
# Creates an onedir backend bundle with embedded Python runtime
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

install_python_packages() {
    if command -v uv &>/dev/null; then
        uv pip install --python "$PYTHON_BIN" "$@"
    else
        "$PYTHON_BIN" -m pip install "$@"
    fi
}

uninstall_python_package() {
    if command -v uv &>/dev/null; then
        uv pip uninstall --python "$PYTHON_BIN" -y "$1" >/dev/null 2>&1 || true
    else
        "$PYTHON_BIN" -m pip uninstall -y "$1" >/dev/null 2>&1 || true
    fi
}

# Install PyInstaller if not present
echo "== Installing PyInstaller =="
if ! "$PYTHON_BIN" -c "import PyInstaller" 2> /dev/null; then
    echo "Installing PyInstaller..."
    install_python_packages "pyinstaller>=6.0.0"
fi
echo "PyInstaller installed"

# Install project dependencies (ensures ALL runtime deps are importable)
echo "== Installing project dependencies =="
install_python_packages -e ".[full]"
echo "Project dependencies installed with full extras"

# Fix agent-client-protocol namespace collision
# PyPI has an empty 'acp' stub that shadows the real package
if ! "$PYTHON_BIN" -c "from acp import Agent" 2> /dev/null; then
    echo "Fixing agent-client-protocol namespace..."
    uninstall_python_package acp
    install_python_packages "agent-client-protocol>=0.9.0,<0.11.0"
fi
echo ""

# Run PyInstaller
echo "== Running PyInstaller =="
echo "Building onedir backend bundle..."

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

echo "PyInstaller build complete"
echo ""

# Verify output
BACKEND_DIR="${DIST}/pyinstaller/qwenpaw-backend"
BACKEND_EXE="${BACKEND_DIR}/qwenpaw-backend"
CLI_EXE="${BACKEND_DIR}/qwenpaw"
if [ ! -d "${BACKEND_DIR}" ]; then
    echo "ERROR: Backend bundle directory not found at ${BACKEND_DIR}"
    exit 1
fi
if [ ! -f "${BACKEND_EXE}" ]; then
    echo "ERROR: Backend executable not found at ${BACKEND_EXE}"
    exit 1
fi
if [ ! -f "${CLI_EXE}" ]; then
    echo "ERROR: CLI executable not found at ${CLI_EXE}"
    exit 1
fi

echo "Backend bundle created: ${BACKEND_DIR}"

# Get size
SIZE=$(du -sh "${BACKEND_DIR}" | cut -f1)
echo "Bundle size: ${SIZE}"
echo ""

# Copy to Tauri resources directory
echo "== Copying to Tauri binaries directory =="
BINARIES_DIR="${REPO_ROOT}/console/src-tauri/binaries"
mkdir -p "${BINARIES_DIR}"

DEST="${BINARIES_DIR}/qwenpaw-backend"
mkdir -p "${DEST}"
find "${DEST}" -mindepth 1 -exec rm -rf {} +
cp -R "${BACKEND_DIR}/." "${DEST}/"
chmod +x "${DEST}/qwenpaw-backend"
chmod +x "${DEST}/qwenpaw"
echo "Copied to: ${DEST}"
echo ""

# Stage a standalone CPython (same X.Y/arch as this build's interpreter) so the
# frozen backend can install third-party plugin dependencies at runtime.
echo "== Staging bundled Python runtime =="
"$PYTHON_BIN" "${REPO_ROOT}/scripts/pack-tauri/stage_python_runtime.py" \
    --dest "${BINARIES_DIR}/python-runtime"
echo ""

echo "== Staging bundled Node runtime =="
"$PYTHON_BIN" "${REPO_ROOT}/scripts/pack-tauri/stage_node_runtime.py" \
    --dest "${BINARIES_DIR}/node-runtime"
echo ""

# Build and stage the Computer Use helper next to the backend so the desktop
# runtime resolves it from resources/binaries/qwenpaw-backend. macOS only: the
# helper's OS leaves are gated to Windows/macOS, so it does not build on Linux.
# Staging here (before the backend dir is code-signed) lets the signing step
# cover the helper Mach-O as well.
if [ "$(uname -s)" = "Darwin" ]; then
    echo "== Building Computer Use helper =="
    if ! command -v cargo &>/dev/null; then
        echo "ERROR: cargo not found; Rust toolchain is required to build qwenpaw-computer-use-helper"
        exit 1
    fi
    TAURI_DIR="${REPO_ROOT}/console/src-tauri"
    (cd "${TAURI_DIR}" && cargo build --release --bin qwenpaw-computer-use-helper)
    TARGET_DIR="${CARGO_TARGET_DIR:-${TAURI_DIR}/target}"
    # Cargo ran in TAURI_DIR, so a relative CARGO_TARGET_DIR is relative to
    # there and not to wherever this script was invoked from. Without this the
    # helper builds and then cannot be found, which the PowerShell packer
    # already accounts for.
    case "${TARGET_DIR}" in
        /*) ;;
        *) TARGET_DIR="${TAURI_DIR}/${TARGET_DIR}" ;;
    esac
    HELPER_BIN="${TARGET_DIR}/release/qwenpaw-computer-use-helper"
    if [ ! -f "${HELPER_BIN}" ]; then
        echo "ERROR: Computer Use helper not found at ${HELPER_BIN}"
        exit 1
    fi
    cp -f "${HELPER_BIN}" "${DEST}/qwenpaw-computer-use-helper"
    chmod +x "${DEST}/qwenpaw-computer-use-helper"
    echo "Computer Use helper staged: ${DEST}/qwenpaw-computer-use-helper"
    echo ""
fi

echo "========================================="
echo "PyInstaller Build Complete!"
echo "========================================="
echo "Output:"
echo "  Bundle: ${BACKEND_DIR}"
echo "  Tauri resource: ${DEST}"
echo ""
