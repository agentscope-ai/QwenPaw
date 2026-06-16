#!/usr/bin/env bash
# Build a conda-packed QwenPaw backend environment for Tauri (macOS/Linux).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

DIST="${DIST:-dist}"
if [[ "$DIST" != /* ]]; then
  DIST="${REPO_ROOT}/${DIST}"
fi
OUTPUT_DIR="${1:-${REPO_ROOT}/console/src-tauri/binaries/qwenpaw-backend}"
if [[ "$OUTPUT_DIR" != /* ]]; then
  OUTPUT_DIR="${REPO_ROOT}/${OUTPUT_DIR}"
fi

ARCHIVE="${DIST}/qwenpaw-env.tar.gz"
PACK_DIR="${REPO_ROOT}/scripts/pack"
BUILD_COMMON="${PACK_DIR}/build_common.py"
REUSE_PACKED_ENV="${QWENPAW_REUSE_PACKED_ENV:-0}"
COMPILEALL_MODE="$(
  printf '%s' "${QWENPAW_TAURI_COMPILEALL:-0}" | tr '[:upper:]' '[:lower:]'
)"
VERSION="$(
  sed -n 's/^__version__[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' \
    src/qwenpaw/__version__.py
)"

ensure_wheel() {
  mkdir -p "$DIST"
  if compgen -G "${DIST}/qwenpaw-${VERSION}-*.whl" >/dev/null; then
    echo "dist/ already has wheel for version ${VERSION}, skipping wheel build."
    return
  fi
  rm -f "${DIST}"/qwenpaw-*.whl
  bash scripts/wheel_build.sh
}

ensure_packed_archive() {
  if [[ "$REUSE_PACKED_ENV" == "1" ]]; then
    echo "== Using existing conda-packed env archive =="
    if [[ ! -f "$ARCHIVE" ]]; then
      echo "ERROR: QWENPAW_REUSE_PACKED_ENV=1 but archive was not found: $ARCHIVE" >&2
      exit 1
    fi
    echo "Reusing archive: ${ARCHIVE}"
    return
  fi

  ensure_wheel

  echo "== Building conda-packed env =="
  python "$BUILD_COMMON" --output "$ARCHIVE" --format tar.gz
}

resolve_env_root() {
  local root="$1"
  if [[ -x "${root}/bin/python" ]]; then
    printf '%s\n' "$root"
    return
  fi
  local nested
  for nested in "$root"/*; do
    if [[ -d "$nested" && -x "${nested}/bin/python" ]]; then
      printf '%s\n' "$nested"
      return
    fi
  done
  echo "ERROR: bin/python not found in unpacked env: $root" >&2
  exit 1
}

prepare_output_dir() {
  if [[ -z "$OUTPUT_DIR" || "$OUTPUT_DIR" == "/" ]]; then
    echo "ERROR: unsafe Tauri backend output directory: $OUTPUT_DIR" >&2
    exit 1
  fi
  mkdir -p "$OUTPUT_DIR"
  find "$OUTPUT_DIR" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
}

canonical_dir() {
  (cd "$1" && pwd -P)
}

move_env_root_to_output_dir() {
  local env_root="$1"
  local dest="$2"
  local env_root_real
  local dest_real
  local flatten_dir

  env_root_real="$(canonical_dir "$env_root")"
  dest_real="$(canonical_dir "$dest")"
  if [[ "$env_root_real" == "$dest_real" ]]; then
    printf '%s\n' "$dest_real"
    return
  fi

  flatten_dir="$(mktemp -d "${dest_real}.flatten.XXXXXX")"
  find "$env_root_real" -mindepth 1 -maxdepth 1 -exec mv {} "$flatten_dir/" \;
  find "$dest_real" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
  find "$flatten_dir" -mindepth 1 -maxdepth 1 -exec mv {} "$dest_real/" \;
  rmdir "$flatten_dir"
  printf '%s\n' "$dest_real"
}

invoke_optional_compileall() {
  local env_root="$1"
  local python_exe="${env_root}/bin/python"

  case "$COMPILEALL_MODE" in
    1|true|yes|full)
      echo "== Pre-compiling Python bytecode =="
      "$python_exe" -m compileall -q -j 0 "$env_root" || \
        echo "WARN: bytecode compilation had errors" >&2
      ;;
    qwenpaw)
      local package_dir
      package_dir="$(find "${env_root}/lib" -path '*/site-packages/qwenpaw' -type d -print -quit 2>/dev/null || true)"
      if [[ -n "$package_dir" ]]; then
        echo "== Pre-compiling QwenPaw Python bytecode =="
        "$python_exe" -m compileall -q "$package_dir" || \
          echo "WARN: QwenPaw bytecode compilation had errors" >&2
      else
        echo "WARN: QwenPaw package not found for bytecode compilation" >&2
      fi
      ;;
    *)
      echo "== Skipping Python bytecode pre-compilation =="
      echo "Set QWENPAW_TAURI_COMPILEALL=full to enable full compileall."
      ;;
  esac
}

echo "========================================="
echo "QwenPaw Tauri Backend - conda-pack"
echo "========================================="
echo "Version: ${VERSION}"
echo "Output:  ${OUTPUT_DIR}"
echo ""

if ! command -v conda >/dev/null 2>&1 && [[ -z "${CONDA_EXE:-}" ]]; then
  echo "ERROR: conda not found on PATH and CONDA_EXE is not set" >&2
  exit 1
fi
command -v python >/dev/null 2>&1 || {
  echo "ERROR: python not found on PATH" >&2
  exit 1
}
[[ -f "$BUILD_COMMON" ]] || {
  echo "ERROR: build_common.py not found: $BUILD_COMMON" >&2
  exit 1
}

ensure_packed_archive

echo "== Unpacking env to Tauri resource directory =="
prepare_output_dir
tar -xzf "$ARCHIVE" -C "$OUTPUT_DIR"
ENV_ROOT="$(resolve_env_root "$OUTPUT_DIR")"
ENV_ROOT="$(move_env_root_to_output_dir "$ENV_ROOT" "$OUTPUT_DIR")"
echo "Env root: ${ENV_ROOT}"

if [[ -x "${ENV_ROOT}/bin/conda-unpack" ]]; then
  echo "== Running conda-unpack =="
  (cd "$ENV_ROOT" && ./bin/conda-unpack)
else
  echo "WARN: conda-unpack not found at ${ENV_ROOT}/bin/conda-unpack" >&2
fi

invoke_optional_compileall "$ENV_ROOT"
chmod +x "${OUTPUT_DIR}/bin/python"
[[ -x "${OUTPUT_DIR}/bin/qwenpaw" ]] && chmod +x "${OUTPUT_DIR}/bin/qwenpaw"

[[ -x "${OUTPUT_DIR}/bin/python" ]] || {
  echo "ERROR: bin/python not found in Tauri backend resource: $OUTPUT_DIR" >&2
  exit 1
}

SIZE="$(du -sh "$OUTPUT_DIR" | cut -f1)"
echo "Backend resource ready: ${OUTPUT_DIR}"
echo "Resource size: ${SIZE}"
