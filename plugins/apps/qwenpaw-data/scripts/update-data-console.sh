#!/usr/bin/env bash
# Refresh the tracked Data console snapshot from a published console wheel.
#
# Inputs:
#   QWENPAW_DATA_CONSOLE_WHEEL    path to a qwenpaw-data-console wheel
#   QWENPAW_DATA_CONSOLE_VERSION  version to download from PyPI when no wheel is given
#   PYTHON                        interpreter used for download/extraction (default: python3)
#
# The wheel must contain qwenpaw_data/console/static/chat-embed, produced by
# QwenPaw-Data's scripts/build_console.py. The snapshot stays served same-origin
# by the QwenPaw gateway, so paw-bridge.js is injected before the module bundle.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DEST_DIR="${QWENPAW_DATA_CONSOLE_DEST:-$APP_DIR/ui/public/data-console}"
BRIDGE_FILE="$SCRIPT_DIR/data-console/paw-bridge.js"
VERIFY_SCRIPT="$SCRIPT_DIR/verify-data-console.py"
GATEWAY_BASE="/api/qwenpaw-data/engine"
CONTEXT_CONSOLE_URL="/api/frontend_plugin/qwenpaw-data/files/ui/dist/context-console/index.html#"
PYTHON="${PYTHON:-python3}"
TEMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/qwenpaw-data-console.XXXXXX")"
NEW_DEST="${DEST_DIR}.new.$$"
OLD_DEST="${DEST_DIR}.old.$$"

cleanup() {
  rm -rf "$TEMP_ROOT" "$NEW_DEST"
  if [[ -e "$OLD_DEST" && ! -e "$DEST_DIR" ]]; then
    mv "$OLD_DEST" "$DEST_DIR"
  else
    rm -rf "$OLD_DEST"
  fi
}
trap cleanup EXIT

for required in "$BRIDGE_FILE" "$VERIFY_SCRIPT"; do
  if [[ ! -f "$required" ]]; then
    echo "Missing update input: $required" >&2
    exit 1
  fi
done

WHEEL="${QWENPAW_DATA_CONSOLE_WHEEL:-}"
VERSION="${QWENPAW_DATA_CONSOLE_VERSION:-}"
if [[ -z "$WHEEL" ]]; then
  if [[ -z "$VERSION" ]]; then
    echo "Set QWENPAW_DATA_CONSOLE_WHEEL or QWENPAW_DATA_CONSOLE_VERSION." >&2
    exit 1
  fi
  mkdir -p "$TEMP_ROOT/wheels"
  "$PYTHON" -m pip download --quiet --no-deps --only-binary=:all: \
    --dest "$TEMP_ROOT/wheels" "qwenpaw-data-console==$VERSION"
  WHEEL="$(ls "$TEMP_ROOT"/wheels/qwenpaw_data_console-*.whl | head -1)"
fi
if [[ ! -f "$WHEEL" ]]; then
  echo "Console wheel not found: $WHEEL" >&2
  exit 1
fi

echo "==> Extracting Console embed assets from $(basename "$WHEEL")"
"$PYTHON" - "$WHEEL" "$TEMP_ROOT/extracted" <<'PY'
import sys
import zipfile
from pathlib import Path

wheel = Path(sys.argv[1])
target = Path(sys.argv[2])
prefix = "qwenpaw_data/console/static/chat-embed/"
with zipfile.ZipFile(wheel) as archive:
    entries = [
        name
        for name in archive.namelist()
        if name.startswith(prefix) and not name.endswith("/")
    ]
    if not any(name.endswith("/index.html") for name in entries):
        raise SystemExit(
            "Wheel has no static/chat-embed assets. Publish a Console built with "
            "QwenPaw-Data's scripts/build_console.py (embed mode)."
        )
    for name in entries:
        relative = Path(name)
        if "\\" in name or ".." in relative.parts or relative.is_absolute():
            raise SystemExit(f"Unsafe wheel member: {name}")
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(archive.read(name))
PY
EMBED_DIR="$TEMP_ROOT/extracted/qwenpaw_data/console/static/chat-embed"
if [[ ! -f "$EMBED_DIR/index.html" ]]; then
  echo "Extracted embed assets are incomplete: $EMBED_DIR" >&2
  exit 1
fi

STAGE_DIR="$TEMP_ROOT/snapshot"
mkdir -p "$STAGE_DIR"
cp -R "$EMBED_DIR/." "$STAGE_DIR/"
cp "$BRIDGE_FILE" "$STAGE_DIR/paw-bridge.js"

"$PYTHON" - "$STAGE_DIR" <<'PY'
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
index = root / "index.html"
html = index.read_text(encoding="utf-8")
if html.count("<head>") != 1:
    raise SystemExit("Expected exactly one <head> in Data console index.html")
if '<script src="./paw-bridge.js"></script>' not in html:
    html = html.replace(
        "<head>",
        '<head><script src="./paw-bridge.js"></script>'
        "<style>html,body,#root{height:100%;margin:0}</style>",
        1,
    )
# The embed bundle receives runtime config from paw-bridge.js; a standalone
# config endpoint would be a root-absolute request under the gateway path.
html = re.sub(
    r'\s*<script src="(?:/|\./)console-config\.js"></script>', "", html
)
index.write_text(html, encoding="utf-8")
PY

PACKAGE_VERSION="$("$PYTHON" - "$WHEEL" <<'PY'
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1]) as archive:
    name = next(
        (
            member
            for member in archive.namelist()
            if member.endswith(".dist-info/METADATA")
        ),
        None,
    )
    if name is None:
        raise SystemExit("Wheel has no METADATA")
    for line in archive.read(name).decode("utf-8").splitlines():
        if line.startswith("Version:"):
            print(line.split(":", 1)[1].strip())
            break
    else:
        raise SystemExit("Wheel METADATA has no Version")
PY
)"

file_sha256() {
  "$PYTHON" - "$1" <<'PY'
from hashlib import sha256
from pathlib import Path
import sys

print(sha256(Path(sys.argv[1]).read_bytes()).hexdigest())
PY
}

WHEEL_SHA256="$(file_sha256 "$WHEEL")"
BRIDGE_SHA256="$(file_sha256 "$BRIDGE_FILE")"
cat > "$STAGE_DIR/BUILD_INFO" <<EOF
format_version=2
source_project=qwenpaw-data-console
package_version=$PACKAGE_VERSION
wheel_filename=$(basename "$WHEEL")
wheel_sha256=$WHEEL_SHA256
bridge_sha256=$BRIDGE_SHA256
gateway_base=$GATEWAY_BASE
context_console_url=$CONTEXT_CONSOLE_URL
EOF

"$PYTHON" "$VERIFY_SCRIPT" "$STAGE_DIR" \
  --canonical-bridge "$BRIDGE_FILE" \
  --write-checksums

rm -rf "$NEW_DEST" "$OLD_DEST"
cp -R "$STAGE_DIR" "$NEW_DEST"
if [[ -e "$DEST_DIR" ]]; then
  mv "$DEST_DIR" "$OLD_DEST"
fi
mv "$NEW_DEST" "$DEST_DIR"
rm -rf "$OLD_DEST"

echo "==> Updated tracked Data console snapshot from $PACKAGE_VERSION"
echo "    Run 'npm --prefix ui run build' to refresh ui/dist."
