#!/usr/bin/env bash
# Refresh the tracked Data console snapshot from an authorized Cloud checkout.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DATA_CLOUD_DIR="${DATA_CLOUD_DIR:-$HOME/dev/datapaw/QwenPaw-Data-Cloud}"
DATA_CLOUD_REF="${DATA_CLOUD_REF:-HEAD}"
FRONTEND_PATH="packages/datapaw-host-core/frontend"
UI_TOKENS_PATH="packages/datapaw-ui-tokens"
DEST_DIR="$APP_DIR/ui/public/data-console"
BRIDGE_FILE="$SCRIPT_DIR/data-console/paw-bridge.js"
PATCH_FILE="$SCRIPT_DIR/data-console/patches/console-embed.patch"
VERIFY_SCRIPT="$SCRIPT_DIR/verify-data-console.py"
GATEWAY_BASE="/api/qwenpaw-data/engine"
CONTEXT_CONSOLE_URL="/api/frontend_plugin/qwenpaw-data/files/ui/dist/context-console/index.html#"
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

for required in "$BRIDGE_FILE" "$PATCH_FILE" "$VERIFY_SCRIPT"; do
  if [[ ! -f "$required" ]]; then
    echo "Missing update input: $required" >&2
    exit 1
  fi
done
if ! git -C "$DATA_CLOUD_DIR" rev-parse --git-dir >/dev/null 2>&1; then
  echo "QwenPaw-Data-Cloud checkout not found: $DATA_CLOUD_DIR" >&2
  echo "Set DATA_CLOUD_DIR to an authorized checkout." >&2
  exit 1
fi

SOURCE_COMMIT="$(git -C "$DATA_CLOUD_DIR" rev-parse "${DATA_CLOUD_REF}^{commit}")"
echo "==> Exporting Data console source at $SOURCE_COMMIT"
git -C "$DATA_CLOUD_DIR" archive "$SOURCE_COMMIT" \
  "$FRONTEND_PATH" "$UI_TOKENS_PATH" | tar -x -C "$TEMP_ROOT"
FRONTEND_DIR="$TEMP_ROOT/$FRONTEND_PATH"
UI_TOKENS_DIR="$TEMP_ROOT/$UI_TOKENS_PATH"
if [[ ! -f "$FRONTEND_DIR/package.json" || ! -f "$FRONTEND_DIR/package-lock.json" ]]; then
  echo "Pinned Data console source or lockfile is missing at $SOURCE_COMMIT" >&2
  exit 1
fi
if [[ ! -f "$UI_TOKENS_DIR/package.json" ]]; then
  echo "Pinned Data console UI tokens are missing at $SOURCE_COMMIT" >&2
  exit 1
fi

git -C "$TEMP_ROOT" init -q
if ! git -C "$TEMP_ROOT" apply --check "$PATCH_FILE"; then
  echo "console-embed.patch does not apply to $SOURCE_COMMIT." >&2
  echo "Refresh the integration patch before updating the snapshot." >&2
  exit 1
fi
git -C "$TEMP_ROOT" apply "$PATCH_FILE"

(
  cd "$FRONTEND_DIR"
  npm ci --no-audit --no-fund
  mkdir -p node_modules/@datapaw
  ln -s "$UI_TOKENS_DIR" node_modules/@datapaw/ui-tokens
  VITE_API_BASE_URL="$GATEWAY_BASE" \
  VITE_CONTEXT_FRONTEND_URL="$CONTEXT_CONSOLE_URL" \
    npm run build -- --base=./
)

STAGE_DIR="$TEMP_ROOT/snapshot"
mkdir -p "$STAGE_DIR"
cp -R "$FRONTEND_DIR/dist/." "$STAGE_DIR/"
cp "$BRIDGE_FILE" "$STAGE_DIR/paw-bridge.js"

python3 - "$STAGE_DIR" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
index = root / "index.html"
html = index.read_text(encoding="utf-8")
needle = "<head>"
injection = '<head><script src="./paw-bridge.js"></script><style>html,body,#root{height:100%;margin:0}</style>'
if html.count(needle) != 1:
    raise SystemExit("Expected exactly one <head> in Data console index.html")
index.write_text(html.replace(needle, injection, 1), encoding="utf-8")

assets = [path.name for path in root.iterdir() if path.suffix in {".png", ".mp4"}]
for path in root.rglob("*"):
    if not path.is_file() or path.suffix not in {".html", ".js", ".css"}:
        continue
    text = path.read_text(encoding="utf-8")
    updated = text
    for name in assets:
        updated = updated.replace(f'"/{name}', f'"./{name}')
        updated = updated.replace(f"'/{name}", f"'./{name}")
    updated = updated.replace(
        "media.src = '/snow-leopard-loading'",
        "media.src = './snow-leopard-loading'",
    )
    updated = updated.replace(
        "`/snow-leopard-loading",
        "`./snow-leopard-loading",
    )
    if updated != text:
        path.write_text(updated, encoding="utf-8")
PY

file_sha256() {
  python3 - "$1" <<'PY'
from hashlib import sha256
from pathlib import Path
import sys

print(sha256(Path(sys.argv[1]).read_bytes()).hexdigest())
PY
}

SOURCE_LOCK_SHA256="$(file_sha256 "$FRONTEND_DIR/package-lock.json")"
PATCH_SHA256="$(file_sha256 "$PATCH_FILE")"
BRIDGE_SHA256="$(file_sha256 "$BRIDGE_FILE")"
cat > "$STAGE_DIR/BUILD_INFO" <<EOF
format_version=1
source_project=QwenPaw-Data-Cloud
source_commit=$SOURCE_COMMIT
source_lock_sha256=$SOURCE_LOCK_SHA256
patch_sha256=$PATCH_SHA256
bridge_sha256=$BRIDGE_SHA256
gateway_base=$GATEWAY_BASE
context_console_url=$CONTEXT_CONSOLE_URL
EOF

python3 "$VERIFY_SCRIPT" "$STAGE_DIR" \
  --canonical-bridge "$BRIDGE_FILE" \
  --canonical-patch "$PATCH_FILE" \
  --write-checksums

rm -rf "$NEW_DEST" "$OLD_DEST"
cp -R "$STAGE_DIR" "$NEW_DEST"
if [[ -e "$DEST_DIR" ]]; then
  mv "$DEST_DIR" "$OLD_DEST"
fi
mv "$NEW_DEST" "$DEST_DIR"
rm -rf "$OLD_DEST"

echo "==> Updated tracked Data console snapshot from $SOURCE_COMMIT"
echo "    Run 'npm --prefix ui run build' to refresh ui/dist."
