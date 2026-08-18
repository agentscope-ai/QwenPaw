#!/usr/bin/env bash
#
# sync-context-ui.sh — build the datapaw-context console frontend and vendor
# the output into this plugin as an embeddable static SPA.
#
# The default source is the public QwenPaw-Data checkout (matches the
# datapaw-* packages published on PyPI and installed in the managed service
# runtime). Point DATAPAW_SOURCE_DIR at an internal QwenPaw-Data-Cloud
# checkout to build its frontend superset instead; both repos share the
# packages/datapaw-context/frontend layout.
#
# The build is patched to use hash routing (static file serving cannot
# rewrite deep-link paths) and pointed at the plugin's context gateway.
# A small classic-script bridge (scripts/context-console/paw-bridge.js) is
# injected into index.html so the same-origin iframe can attach the QwenPaw
# host auth token to gateway requests.
#
# Usage:
#   scripts/sync-context-ui.sh
#
# Environment:
#   DATAPAW_SOURCE_DIR    Frontend source checkout (default: ~/dev/QwenPaw-Data)
#   DATAPAW_GATEWAY_BASE  Gateway base path (default: /api/datapaw/context)
#   FORCE_INSTALL=1       Re-run the npm install even if node_modules exists

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DATAPAW_SOURCE_DIR="${DATAPAW_SOURCE_DIR:-${DATA_CLOUD_DIR:-$HOME/dev/QwenPaw-Data}}"
FRONTEND_DIR="$DATAPAW_SOURCE_DIR/packages/datapaw-context/frontend"
ROUTER_FILE="$FRONTEND_DIR/src/router/index.tsx"
DEST_DIR="$APP_DIR/ui/public/context-console"
BRIDGE_FILE="$SCRIPT_DIR/context-console/paw-bridge.js"
GATEWAY_BASE="${DATAPAW_GATEWAY_BASE:-/api/datapaw/context}"

if [[ ! -f "$FRONTEND_DIR/package.json" ]]; then
  echo "Context console frontend was not found: $FRONTEND_DIR" >&2
  echo "Set DATAPAW_SOURCE_DIR to a QwenPaw-Data (or Data-Cloud) checkout." >&2
  exit 1
fi
if [[ ! -f "$BRIDGE_FILE" ]]; then
  echo "Bridge script is missing: $BRIDGE_FILE" >&2
  exit 1
fi

SOURCE_COMMIT="$(git -C "$DATAPAW_SOURCE_DIR" rev-parse --short HEAD)"
SOURCE_BRANCH="$(git -C "$DATAPAW_SOURCE_DIR" rev-parse --abbrev-ref HEAD)"
SOURCE_DIRTY="clean"
# Untracked files are ignored: the internal checkout ships no lockfile, so
# npm install leaves an untracked package-lock.json behind.
if [[ -n "$(git -C "$DATAPAW_SOURCE_DIR" status --porcelain -uno)" ]]; then
  SOURCE_DIRTY="dirty"
  echo "WARNING: $DATAPAW_SOURCE_DIR has uncommitted changes; the build will" \
    "not be reproducible from commit $SOURCE_COMMIT." >&2
fi
echo "==> Building Context console from $SOURCE_BRANCH@$SOURCE_COMMIT ($SOURCE_DIRTY)"

# --- Temporary source patch: hash routing for static hosting ---------------
if ! grep -q "createBrowserRouter" "$ROUTER_FILE"; then
  echo "Expected createBrowserRouter in $ROUTER_FILE; upstream may have" >&2
  echo "changed routers. Review the sync script before continuing." >&2
  exit 1
fi
cp "$ROUTER_FILE" "$ROUTER_FILE.paw-sync.bak"
restore_router() {
  if [[ -f "$ROUTER_FILE.paw-sync.bak" ]]; then
    mv "$ROUTER_FILE.paw-sync.bak" "$ROUTER_FILE"
  fi
}
trap restore_router EXIT
perl -pi -e 's/createBrowserRouter/createHashRouter/g' "$ROUTER_FILE"

# --- Build ------------------------------------------------------------------
pushd "$FRONTEND_DIR" >/dev/null
if [[ ! -d node_modules || "${FORCE_INSTALL:-0}" == "1" ]]; then
  if [[ -f package-lock.json ]]; then
    npm ci --no-audit --no-fund
  else
    # The internal checkout ships no lockfile.
    npm install --no-audit --no-fund
  fi
fi
VITE_API_BASE_URL="$GATEWAY_BASE" \
VITE_AUTH_API_URL="$GATEWAY_BASE" \
  npm run build -- --base=./
popd >/dev/null

restore_router
trap - EXIT

# --- Vendor the output -------------------------------------------------------
rm -rf "$DEST_DIR"
mkdir -p "$DEST_DIR"
cp -R "$FRONTEND_DIR/dist/." "$DEST_DIR/"
cp "$BRIDGE_FILE" "$DEST_DIR/paw-bridge.js"

# Inject the auth bridge before the module bundle (classic scripts in <head>
# always execute before deferred module scripts). Also hide the console's own
# header bar (the plugin shell renders the persistent top banner and hosts the
# language/model-settings actions), reclaim the 56px slot pro-layout's mix
# mode reserves for it on the fixed sider so the divider spans the full
# height, pad the menu so its first item sits level with the page title and
# the shell's first nav row, and center the sider collapse button vertically.
perl -pi -e 's#<head>#<head><script src="./paw-bridge.js"></script><style>.ant-pro-layout-header,.ant-pro-global-header,header.ant-layout-header{display:none !important}.ant-pro-sider-fixed-mix{inset-block-start:0 !important;height:100% !important}.ant-pro-sider .ant-layout-sider-children{padding-block-start:16px !important}.ant-pro-sider-collapsed-button{inset-block-start:50% !important;transform:translateY(-50%) !important}</style>#' \
  "$DEST_DIR/index.html"
if ! grep -q "paw-bridge.js" "$DEST_DIR/index.html"; then
  echo "Failed to inject paw-bridge.js into index.html" >&2
  exit 1
fi

# The layout hardcodes root-absolute image paths (e.g.
# src="/qwenpaw-data-wordmark.png") that bypass the vite --base rewrite and
# 404 when the console is served from a subpath. Rewrite every reference to
# a public-root PNG we vendored so it resolves relative to index.html.
for asset in "$DEST_DIR"/*.png; do
  [[ -f "$asset" ]] || continue
  name="$(basename "$asset")"
  for target in "$DEST_DIR"/assets/*.js "$DEST_DIR"/assets/*.css \
    "$DEST_DIR/index.html"; do
    [[ -f "$target" ]] || continue
    ASSET_NAME="$name" perl -pi -e \
      's#(["\x27])/\Q$ENV{ASSET_NAME}\E#${1}./$ENV{ASSET_NAME}#g' "$target"
  done
done

cat > "$DEST_DIR/BUILD_INFO" <<EOF
source_repo=$DATAPAW_SOURCE_DIR
source_branch=$SOURCE_BRANCH
source_commit=$SOURCE_COMMIT
source_tree=$SOURCE_DIRTY
gateway_base=$GATEWAY_BASE
built_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
patches=createBrowserRouter->createHashRouter
EOF

echo "==> Context console vendored into $DEST_DIR"

# --- Rebuild the plugin UI so the assets land in ui/dist ---------------------
if [[ -d "$APP_DIR/ui/node_modules" ]]; then
  echo "==> Rebuilding the plugin UI bundle"
  (cd "$APP_DIR/ui" && npm run build)
else
  echo "NOTE: run 'npm install && npm run build' in $APP_DIR/ui to publish" \
    "the vendored console into ui/dist."
fi
