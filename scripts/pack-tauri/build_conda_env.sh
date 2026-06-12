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

ARCHIVE="${DIST}/qwenpaw-tauri-env.tar.gz"
UNPACKED="${DIST}/tauri-macos-unpacked"
PACK_DIR="${REPO_ROOT}/scripts/pack"
BUILD_COMMON="${PACK_DIR}/build_common.py"
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

ensure_wheel

echo "== Building conda-packed env =="
python "$BUILD_COMMON" --output "$ARCHIVE" --format tar.gz

echo "== Unpacking env =="
rm -rf "$UNPACKED"
mkdir -p "$UNPACKED"
tar -xzf "$ARCHIVE" -C "$UNPACKED"
ENV_ROOT="$(resolve_env_root "$UNPACKED")"
echo "Env root: ${ENV_ROOT}"

if [[ -x "${ENV_ROOT}/bin/conda-unpack" ]]; then
  echo "== Running conda-unpack =="
  (cd "$ENV_ROOT" && ./bin/conda-unpack)
else
  echo "WARN: conda-unpack not found at ${ENV_ROOT}/bin/conda-unpack" >&2
fi

echo "== Pre-compiling Python bytecode =="
"${ENV_ROOT}/bin/python" -m compileall -q -j 0 "$ENV_ROOT" || \
  echo "WARN: bytecode compilation had errors" >&2

echo "== Copying to Tauri resource directory =="
mkdir -p "$OUTPUT_DIR"
find "$OUTPUT_DIR" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
cp -R "${ENV_ROOT}/." "$OUTPUT_DIR/"
chmod +x "${OUTPUT_DIR}/bin/python"
[[ -x "${OUTPUT_DIR}/bin/qwenpaw" ]] && chmod +x "${OUTPUT_DIR}/bin/qwenpaw"

[[ -x "${OUTPUT_DIR}/bin/python" ]] || {
  echo "ERROR: bin/python not found in Tauri backend resource: $OUTPUT_DIR" >&2
  exit 1
}

SIZE="$(du -sh "$OUTPUT_DIR" | cut -f1)"
echo "Backend resource ready: ${OUTPUT_DIR}"
echo "Resource size: ${SIZE}"
