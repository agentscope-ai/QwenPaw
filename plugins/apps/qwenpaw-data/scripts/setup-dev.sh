#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
QWENPAW_DATA_SOURCE_DIR="${QWENPAW_DATA_SOURCE_DIR:-$HOME/dev/QwenPaw-Data}"
UV_BIN="${UV_BIN:-uv}"

if [[ ! -f "$QWENPAW_DATA_SOURCE_DIR/pyproject.toml" ]]; then
  echo "QwenPaw-Data source workspace not found: $QWENPAW_DATA_SOURCE_DIR" >&2
  echo "Set QWENPAW_DATA_SOURCE_DIR to the QwenPaw-Data checkout." >&2
  exit 1
fi

if ! command -v "$UV_BIN" >/dev/null 2>&1; then
  echo "uv is required to create the isolated QwenPaw-Data environment." >&2
  exit 1
fi

echo "==> Syncing editable QwenPaw-Data workspace packages"
(cd "$QWENPAW_DATA_SOURCE_DIR" && "$UV_BIN" sync --all-packages)

QWENPAW_DATA_PYTHON="$QWENPAW_DATA_SOURCE_DIR/.venv/bin/python"
if [[ ! -x "$QWENPAW_DATA_PYTHON" ]]; then
  echo "QwenPaw-Data Python was not created: $QWENPAW_DATA_PYTHON" >&2
  exit 1
fi

for package_name in qwenpaw-data-context qwenpaw-data-host-core qwenpaw-data-cli qwenpaw-data-skills; do
  "$QWENPAW_DATA_PYTHON" -c \
    'from importlib.metadata import version; import sys; print(f"{sys.argv[1]}=={version(sys.argv[1])}")' \
    "$package_name"
done

mkdir -p "$APP_DIR/.qwenpaw-data-dev"

link_path() {
  local source_path="$1"
  local target_path="$2"
  if [[ -e "$target_path" && ! -L "$target_path" ]]; then
    echo "Refusing to replace non-symlink path: $target_path" >&2
    exit 1
  fi
  ln -sfn "$source_path" "$target_path"
}

link_path "$QWENPAW_DATA_SOURCE_DIR/.venv" "$APP_DIR/.venv-qwenpaw-data"
link_path "$QWENPAW_DATA_SOURCE_DIR" "$APP_DIR/.qwenpaw-data-dev/source"
link_path \
  "$QWENPAW_DATA_SOURCE_DIR/packages/qwenpaw-data-skills/skills" \
  "$APP_DIR/.qwenpaw-data-dev/skills"

echo "==> QwenPaw-Data development packages are ready"
echo "    Python: $QWENPAW_DATA_PYTHON"
echo "    App:    $APP_DIR"
