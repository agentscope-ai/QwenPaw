#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DATAPAW_SOURCE_DIR="${DATAPAW_SOURCE_DIR:-$HOME/dev/QwenPaw-Data}"
UV_BIN="${UV_BIN:-uv}"

if [[ ! -f "$DATAPAW_SOURCE_DIR/pyproject.toml" ]]; then
  echo "QwenPaw-Data source workspace not found: $DATAPAW_SOURCE_DIR" >&2
  echo "Set DATAPAW_SOURCE_DIR to the QwenPaw-Data checkout." >&2
  exit 1
fi

if ! command -v "$UV_BIN" >/dev/null 2>&1; then
  echo "uv is required to create the isolated QwenPaw-Data environment." >&2
  exit 1
fi

echo "==> Syncing editable QwenPaw-Data workspace packages"
(cd "$DATAPAW_SOURCE_DIR" && "$UV_BIN" sync --all-packages)

DATAPAW_PYTHON="$DATAPAW_SOURCE_DIR/.venv/bin/python"
if [[ ! -x "$DATAPAW_PYTHON" ]]; then
  echo "QwenPaw-Data Python was not created: $DATAPAW_PYTHON" >&2
  exit 1
fi

for package_name in datapaw-context datapaw-host-core datapaw-cli datapaw-skills; do
  "$DATAPAW_PYTHON" -c \
    'from importlib.metadata import version; import sys; print(f"{sys.argv[1]}=={version(sys.argv[1])}")' \
    "$package_name"
done

mkdir -p "$APP_DIR/.datapaw-dev"

link_path() {
  local source_path="$1"
  local target_path="$2"
  if [[ -e "$target_path" && ! -L "$target_path" ]]; then
    echo "Refusing to replace non-symlink path: $target_path" >&2
    exit 1
  fi
  ln -sfn "$source_path" "$target_path"
}

link_path "$DATAPAW_SOURCE_DIR/.venv" "$APP_DIR/.venv-datapaw"
link_path "$DATAPAW_SOURCE_DIR" "$APP_DIR/.datapaw-dev/source"
link_path \
  "$DATAPAW_SOURCE_DIR/packages/datapaw-skills/skills" \
  "$APP_DIR/.datapaw-dev/skills"

echo "==> QwenPaw-Data development packages are ready"
echo "    Python: $DATAPAW_PYTHON"
echo "    App:    $APP_DIR"
