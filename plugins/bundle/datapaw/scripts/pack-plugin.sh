#!/usr/bin/env bash
# Pack DataPaw plugin for distribution (see docs/plugins — 插件打包).
# Produces: plugins/bundle/datapaw-<version>.zip
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUNDLE_DIR="$(cd "$ROOT/.." && pwd)"
VERSION="$(python3 -c "import json; print(json.load(open('$ROOT/plugin.json'))['version'])")"
OUT="$BUNDLE_DIR/datapaw-${VERSION}.zip"

echo "==> Building plugin UI (ui/dist/index.js)..."
(cd "$ROOT/ui" && npm ci && npm run build)

echo "==> Creating $OUT ..."
rm -f "$OUT"
(
  cd "$BUNDLE_DIR"
  zip -r "$OUT" datapaw \
    -x "datapaw/frontend/*" \
    -x "datapaw/frontend/**/*" \
    -x "datapaw/ui/src/*" \
    -x "datapaw/ui/src/**/*" \
    -x "datapaw/ui/node_modules/*" \
    -x "datapaw/ui/node_modules/**/*" \
    -x "datapaw/ui/package-lock.json" \
    -x "datapaw/ui/package.json" \
    -x "datapaw/ui/tsconfig.json" \
    -x "datapaw/ui/vite.config.ts" \
    -x "datapaw/**/__pycache__/*" \
    -x "datapaw/.DS_Store" \
    -x "datapaw/**/.DS_Store" \
    -x "datapaw/**/.pytest_cache/*" \
    -x "datapaw/tests/*" \
    -x "datapaw/tests/**/*" \
    -x "datapaw/scripts/*" \
    -x "datapaw/scripts/**/*"
)

echo "==> Done: $OUT ($(du -h "$OUT" | cut -f1))"
echo "Install: qwenpaw plugin install $OUT"
