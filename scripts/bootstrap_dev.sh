#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
PYTHON_VERSION_FILE="$ROOT_DIR/.python-version"
EXTRAS="dev"
RECREATE=0

usage() {
    cat <<'EOF'
Bootstrap CoPaw development environment in the current repository.

Usage:
  bash scripts/bootstrap_dev.sh [--extras dev] [--recreate]

Options:
  --extras <LIST>   Editable install extras, comma-separated. Default: dev
  --recreate        Remove any existing .venv and rebuild it from scratch
  -h, --help        Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --extras)
            if [[ $# -lt 2 ]]; then
                echo "Missing value for --extras" >&2
                usage >&2
                exit 1
            fi
            EXTRAS="$2"
            shift 2
            ;;
        --recreate)
            RECREATE=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

target_python="3.10"
if [[ -f "$PYTHON_VERSION_FILE" ]]; then
    target_python="$(tr -d '[:space:]' < "$PYTHON_VERSION_FILE")"
fi

version_supported() {
    "$1" - <<'PY'
import sys
major, minor = sys.version_info[:2]
raise SystemExit(0 if (major, minor) >= (3, 10) and (major, minor) < (3, 14) else 1)
PY
}

find_python_bin() {
    local candidates=()

    if command -v "python${target_python}" >/dev/null 2>&1; then
        candidates+=("$(command -v "python${target_python}")")
    fi

    for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
        if command -v "$candidate" >/dev/null 2>&1; then
            candidates+=("$(command -v "$candidate")")
        fi
    done

    if command -v pyenv >/dev/null 2>&1; then
        local pyenv_python=""
        pyenv_python="$(pyenv which python 2>/dev/null || true)"
        if [[ -n "$pyenv_python" ]]; then
            candidates+=("$pyenv_python")
        fi
    fi

    local unique=()
    local seen=""
    local candidate=""
    for candidate in "${candidates[@]}"; do
        if [[ -n "$candidate" && ":$seen:" != *":$candidate:"* ]]; then
            unique+=("$candidate")
            seen="$seen:$candidate"
        fi
    done

    for candidate in "${unique[@]}"; do
        if version_supported "$candidate"; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done

    return 1
}

create_with_uv() {
    uv venv "$VENV_DIR" --python "$target_python"
}

create_with_python() {
    local python_bin="$1"
    "$python_bin" -m venv "$VENV_DIR"
}

if [[ $RECREATE -eq 1 && -d "$VENV_DIR" ]]; then
    rm -rf "$VENV_DIR"
fi

if [[ -x "$VENV_DIR/bin/python" ]] && ! version_supported "$VENV_DIR/bin/python"; then
    echo "Existing .venv uses an unsupported Python version. Recreating..."
    rm -rf "$VENV_DIR"
fi

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    if command -v uv >/dev/null 2>&1; then
        echo "Creating .venv with uv (Python $target_python)..."
        create_with_uv
    else
        python_bin="$(find_python_bin || true)"
        if [[ -z "${python_bin:-}" ]]; then
            echo "No supported Python interpreter found (need >=3.10,<3.14)." >&2
            echo "Install Python ${target_python} or uv, then rerun this script." >&2
            exit 1
        fi
        echo "Creating .venv with ${python_bin}..."
        create_with_python "$python_bin"
    fi
fi

echo "Using $("$VENV_DIR/bin/python" -V)"
"$VENV_DIR/bin/python" -m pip install -U pip setuptools wheel
"$VENV_DIR/bin/python" -m pip install -e ".[${EXTRAS}]"

echo
echo "Bootstrap complete."
echo "Activate with: source .venv/bin/activate"
