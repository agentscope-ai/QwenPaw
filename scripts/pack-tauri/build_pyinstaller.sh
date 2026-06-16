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
UV_BIN="$(command -v uv || true)"

# Create venv if missing (prefer uv if available)
PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
if [ ! -f "$PYTHON_BIN" ]; then
    if [ -n "${UV_BIN}" ]; then
        echo "Creating virtual environment with uv..."
        "${UV_BIN}" venv "${REPO_ROOT}/.venv"
    else
        echo "ERROR: Python not found in .venv"
        echo "Please create virtual environment first: python -m venv .venv"
        exit 1
    fi
fi

echo "Python: $("$PYTHON_BIN" --version)"

install_python_packages() {
    if [ -n "${UV_BIN}" ]; then
        "${UV_BIN}" pip install --python "$PYTHON_BIN" "$@"
    else
        "$PYTHON_BIN" -m pip install "$@"
    fi
}

uninstall_python_package() {
    if [ -n "${UV_BIN}" ]; then
        "${UV_BIN}" pip uninstall --python "$PYTHON_BIN" -y "$1" >/dev/null 2>&1 || true
    else
        "$PYTHON_BIN" -m pip uninstall -y "$1" >/dev/null 2>&1 || true
    fi
}

runtime_root_for_python() {
    local python_path="$1"
    local parent
    parent="$(cd "$(dirname "$python_path")" && pwd)"
    case "$(basename "$parent")" in
        bin|Scripts)
            (cd "${parent}/.." && pwd)
            ;;
        *)
            printf '%s\n' "$parent"
            ;;
    esac
}

find_packaged_runtime_python() {
    local runtime_dir="$1"
    for candidate in \
        "${runtime_dir}/bin/python" \
        "${runtime_dir}/bin/python3" \
        "${runtime_dir}/bin/python3.10" \
        "${runtime_dir}/python"; do
        if [ -x "$candidate" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

find_existing_runtime_python() {
    QWENPAW_REPO_ROOT="${REPO_ROOT}" "${PYTHON_BIN}" - <<'PY'
import os
import sys

if sys.version_info[:2] != (3, 10):
    raise SystemExit(0)

repo_root = os.path.realpath(os.environ.get("QWENPAW_REPO_ROOT", ""))
venv_root = os.path.realpath(os.path.join(repo_root, ".venv")) if repo_root else ""
candidates = []


def add(path):
    if path and path not in candidates:
        candidates.append(path)


add(getattr(sys, "_base_executable", ""))
for prefix in (getattr(sys, "base_prefix", ""), getattr(sys, "base_exec_prefix", ""), getattr(sys, "exec_prefix", "")):
    for rel in ("bin/python", "bin/python3", "bin/python3.10", "python"):
        add(os.path.join(prefix, rel))

for candidate in candidates:
    raw = os.path.abspath(candidate)
    real = os.path.realpath(candidate)
    if not os.path.exists(candidate) or not os.access(candidate, os.X_OK):
        continue
    if venv_root and (
        raw == venv_root
        or raw.startswith(venv_root + os.sep)
        or real == venv_root
        or real.startswith(venv_root + os.sep)
    ):
        continue
    print(candidate)
    break
PY
}

prune_python_runtime() {
    local runtime_dir="$1"

    rm -rf \
        "${runtime_dir}/Scripts" \
        "${runtime_dir}/Lib/venv" \
        "${runtime_dir}/Lib/ensurepip" \
        "${runtime_dir}/pythonw" \
        "${runtime_dir}/pythonw.exe" \
        "${runtime_dir}/pythonw.pdb"

    find "${runtime_dir}" -type d \
        \( \
            -path "*/site-packages/pip" -o \
            -path "*/site-packages/pip-*.dist-info" -o \
            -path "*/site-packages/setuptools" -o \
            -path "*/site-packages/setuptools-*.dist-info" -o \
            -path "*/site-packages/wheel" -o \
            -path "*/site-packages/wheel-*.dist-info" -o \
            -path "*/ensurepip" -o \
            -path "*/venv" \
        \) -prune -exec rm -rf {} +

    find "${runtime_dir}" -type f \
        \( \
            -name "pip" -o \
            -name "pip3" -o \
            -name "pip3.*" -o \
            -name "pip.exe" -o \
            -name "pip3.exe" -o \
            -name "pythonw" -o \
            -name "pythonw.exe" \
        \) -delete

    if [ -d "${runtime_dir}/bin" ]; then
        find "${runtime_dir}/bin" -maxdepth 1 \
            \( \
                -name "pip" -o \
                -name "pip3" -o \
                -name "pip3.*" -o \
                -name "idle3" -o \
                -name "idle3.*" -o \
                -name "pydoc3" -o \
                -name "pydoc3.*" -o \
                -name "2to3" -o \
                -name "2to3-*" -o \
                -name "easy_install" -o \
                -name "easy_install-*" -o \
                -name "wheel" -o \
                -name "python-config" -o \
                -name "python3-config" -o \
                -name "python3.*-config" \
            \) -exec rm -f {} +
    fi
}

stage_python_runtime() {
    local destination="$1"

    if [ -z "${UV_BIN}" ]; then
        echo "ERROR: uv is required to stage the Tauri Python runtime"
        exit 1
    fi

    echo "== Staging Python runtime =="
    local runtime_python
    runtime_python="$(find_existing_runtime_python)"

    if [ -n "${runtime_python}" ]; then
        echo "Using existing base Python runtime: ${runtime_python}"
    else
        echo "No existing base Python runtime found; installing managed Python runtime with uv..."
        "${UV_BIN}" python install 3.10
        runtime_python="$("${UV_BIN}" python find --managed-python 3.10)"
    fi

    if [ -z "${runtime_python}" ] || [ ! -x "${runtime_python}" ]; then
        echo "ERROR: Python runtime executable not found: ${runtime_python}"
        exit 1
    fi

    local runtime_root
    runtime_root="$(runtime_root_for_python "${runtime_python}")"
    if [ ! -d "${runtime_root}" ]; then
        echo "ERROR: Python runtime root not found: ${runtime_root}"
        exit 1
    fi

    local runtime_dir="${destination}/python-runtime"
    rm -rf "${runtime_dir}"
    mkdir -p "${runtime_dir}"
    cp -R "${runtime_root}/." "${runtime_dir}/"
    cp "${UV_BIN}" "${runtime_dir}/uv"
    chmod +x "${runtime_dir}/uv"
    prune_python_runtime "${runtime_dir}"

    local packaged_python
    packaged_python="$(find_packaged_runtime_python "${runtime_dir}")" || {
        echo "ERROR: Packaged runtime Python not found in ${runtime_dir}"
        exit 1
    }

    "${packaged_python}" -c "import sys; print('runtime python:', sys.executable); print(sys.version)"
    "${runtime_dir}/uv" --version
    "${runtime_dir}/uv" pip list --python "${packaged_python}" >/dev/null

    echo "Python runtime staged: ${runtime_dir}"
    echo "Runtime size: $(du -sh "${runtime_dir}" | cut -f1)"
    echo ""
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
    install_python_packages agent-client-protocol
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
stage_python_runtime "${DEST}"
chmod +x "${DEST}/qwenpaw-backend"
chmod +x "${DEST}/qwenpaw"
echo "Copied to: ${DEST}"
echo ""

echo "========================================="
echo "PyInstaller Build Complete!"
echo "========================================="
echo "Output:"
echo "  Bundle: ${BACKEND_DIR}"
echo "  Tauri resource: ${DEST}"
echo ""
