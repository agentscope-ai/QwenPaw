#!/usr/bin/env bash
# Build QwenPaw backend with PyInstaller for Tauri sidecar
# Creates an onedir backend bundle with embedded Python runtime
#
# Usage:
#   ./scripts/pack-tauri/build_pyinstaller.sh
#
# Prerequisites:
#   - Python 3.10+ on PATH (used only to bootstrap the bundled runtime)
#   - PyInstaller 6.0+ (will be installed if not present)

set -e

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

DIST="${DIST:-dist}"
BINARIES_DIR="${REPO_ROOT}/console/src-tauri/binaries"
PYTHON_RUNTIME_DIR="${BINARIES_DIR}/python-runtime"
RUNTIME_PYTHON_DIR="${PYTHON_RUNTIME_DIR}/python"
NATIVE_HOST_PYTHON="${RUNTIME_PYTHON_DIR}/bin/python3"
BUILD_VENV="${DIST}/pyinstaller-venv"
PYTHON_BIN="${BUILD_VENV}/bin/python"
VERSION=$(sed -n 's/^__version__[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' src/qwenpaw/__version__.py)

echo "========================================="
echo "QwenPaw PyInstaller Build"
echo "========================================="
echo "Version: ${VERSION}"
echo "Repository: ${REPO_ROOT}"
echo ""

# Check prerequisites
echo "== Checking prerequisites =="

if command -v python3 >/dev/null 2>&1; then
    BOOTSTRAP_PYTHON=$(command -v python3)
elif command -v python >/dev/null 2>&1; then
    BOOTSTRAP_PYTHON=$(command -v python)
else
    echo "ERROR: Python not found on PATH; it is required to stage the bundled runtime"
    exit 1
fi

mkdir -p "${BINARIES_DIR}"

# The staged python-build-standalone runtime is the canonical source for both
# the helper interpreter and the PyInstaller build environment. The PATH
# Python only selects the X.Y version to download and runs the staging script.
echo "== Staging canonical Python runtime =="
"$BOOTSTRAP_PYTHON" "${REPO_ROOT}/scripts/pack-tauri/stage_python_runtime.py" \
    --dest "${PYTHON_RUNTIME_DIR}"
if [ ! -f "$NATIVE_HOST_PYTHON" ]; then
    echo "ERROR: Bundled Python interpreter not found at ${NATIVE_HOST_PYTHON}"
    exit 1
fi

echo "== Creating PyInstaller build environment =="
"$NATIVE_HOST_PYTHON" -m venv --clear "$BUILD_VENV"

echo "Python: $("$PYTHON_BIN" --version)"
echo ""

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
# Pin setuptools <82: lark-oapi still calls pkg_resources.declare_namespace
# at import time. A *fresh* install of setuptools >= 82 removes pkg_resources
# wholesale, so lark-oapi's except-ImportError fallback (pkgutil.extend_path)
# kicks in and the import works. The proven failure mode is an *in-place*
# upgrade of a legacy setuptools (seen on the macOS CI runners, and possible
# in any environment upgrading an existing install): it can leave a
# half-removed pkg_resources (module present, declare_namespace gone), which
# raises an AttributeError the fallback does not catch — crashing the Feishu
# channel. The pin keeps every environment in the known-good state.
install_python_packages -e ".[full]" "setuptools<82"
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
MODEL_CATALOG="${BACKEND_DIR}/_internal/qwenpaw/providers/data/model_catalog.json"
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
if [ ! -f "${MODEL_CATALOG}" ]; then
    echo "ERROR: Model catalog not found at ${MODEL_CATALOG}"
    exit 1
fi

echo "Backend bundle created: ${BACKEND_DIR}"

# Get size
SIZE=$(du -sh "${BACKEND_DIR}" | cut -f1)
echo "Bundle size: ${SIZE}"
echo ""

# Copy to Tauri resources directory
echo "== Copying to Tauri binaries directory =="
DEST="${BINARIES_DIR}/qwenpaw-backend"
rm -rf "${DEST}"
mkdir -p "${DEST}"
cp -R "${BACKEND_DIR}/." "${DEST}/"
chmod +x "${DEST}/qwenpaw-backend"
chmod +x "${DEST}/qwenpaw"
echo "Copied to: ${DEST}"
echo ""

# The Chrome Native Messaging host runs under this standalone interpreter,
# outside the PyInstaller backend, so its dependencies must be installed here.
echo "== Installing bundled Python helper dependencies =="
"$NATIVE_HOST_PYTHON" -m pip install \
    --disable-pip-version-check \
    --no-input \
    --no-deps \
    --only-binary=:all: \
    -r "${REPO_ROOT}/scripts/pack-tauri/native-host-requirements.txt"
"$NATIVE_HOST_PYTHON" \
    "${REPO_ROOT}/plugins/bundle/chrome/assets/scripts/nm_host.py" \
    --check-runtime
echo ""

echo "== Staging bundled Node runtime =="
"$PYTHON_BIN" "${REPO_ROOT}/scripts/pack-tauri/stage_node_runtime.py" \
    --dest "${BINARIES_DIR}/node-runtime"
echo ""

echo "========================================="
echo "PyInstaller Build Complete!"
echo "========================================="
echo "Output:"
echo "  Bundle: ${BACKEND_DIR}"
echo "  Tauri resource: ${DEST}"
echo ""
