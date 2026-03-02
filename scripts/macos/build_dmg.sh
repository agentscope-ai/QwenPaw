#!/usr/bin/env bash
# Build CoPaw as a macOS .app and DMG for distribution.
# Run from repo root: bash scripts/macos/build_dmg.sh [version]
#
# Prerequisites: macOS, Node.js, Python 3.10+, pip install pyinstaller
# Output: dist/CoPaw.app, dist/CoPaw-<version>.dmg

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

VERSION="${1:-}"
VERSION="${VERSION#v}"
if [[ -z "$VERSION" ]]; then
  VERSION=$(python3 -c "from src.copaw.__version__ import __version__; print(__version__)" 2>/dev/null || echo "0.0.0")
fi

CONSOLE_DIR="$REPO_ROOT/console"
CONSOLE_DEST="$REPO_ROOT/src/copaw/console"
DIST_DIR="$REPO_ROOT/dist"
APP_NAME="CoPaw"
DMG_NAME="${APP_NAME}-${VERSION}"
MACOSX_DEPLOYMENT_TARGET="${MACOSX_DEPLOYMENT_TARGET:-10.15}"

echo "[build_dmg] Version: $VERSION"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "[build_dmg] ERROR: This script must run on macOS." >&2
  exit 1
fi

echo "[build_dmg] Building console..."
(cd "$CONSOLE_DIR" && npm ci && npm run build)
rm -rf "$CONSOLE_DEST"
mkdir -p "$CONSOLE_DEST"
cp -R "$CONSOLE_DIR/dist/"* "$CONSOLE_DEST/"
if [[ ! -f "$CONSOLE_DEST/index.html" ]]; then
  echo "[build_dmg] ERROR: console build did not produce index.html." >&2
  exit 1
fi

if [[ -d "$REPO_ROOT/.venv" ]]; then
  PYTHON="$REPO_ROOT/.venv/bin/python"
else
  PYTHON="${PYTHON:-python3}"
fi
if ! "$PYTHON" -m pip --version &>/dev/null; then
  echo "[build_dmg] Bootstrapping pip..."
  "$PYTHON" -m ensurepip --upgrade
fi
"$PYTHON" -m pip install --quiet -e ".[dev]"
"$PYTHON" -m pip install --quiet pyinstaller pywebview

export MACOSX_DEPLOYMENT_TARGET
rm -rf "$REPO_ROOT/build" "$DIST_DIR/$APP_NAME"
PYINSTALLER_OUT="$DIST_DIR/$APP_NAME"

# PyInstaller sometimes hangs after "Build complete" when building GUI (runw).
# Wait for exe and runtime (base_library.zip or full _internal) then allow exit or kill.
echo "[build_dmg] Running PyInstaller..."
"$PYTHON" -m PyInstaller --noconfirm --clean "scripts/macos/copaw.spec" &
PYPID=$!
NEED_KILL=true
for _ in $(seq 1 200); do
  sleep 2
  if [[ -f "$PYINSTALLER_OUT/$APP_NAME" ]]; then
    if [[ -f "$PYINSTALLER_OUT/base_library.zip" ]] || \
       [[ -d "$PYINSTALLER_OUT/_internal" && -f "$PYINSTALLER_OUT/_internal/libpython"* ]]; then
      sleep 2
      if ! kill -0 "$PYPID" 2>/dev/null; then
        NEED_KILL=false
      fi
      kill "$PYPID" 2>/dev/null || true
      wait "$PYPID" 2>/dev/null || true
      break
    fi
  fi
  if ! kill -0 "$PYPID" 2>/dev/null; then
    wait "$PYPID" 2>/dev/null || true
    NEED_KILL=false
    break
  fi
done

if [[ ! -f "$PYINSTALLER_OUT/$APP_NAME" ]]; then
  echo "[build_dmg] ERROR: PyInstaller did not produce $PYINSTALLER_OUT/$APP_NAME" >&2
  kill "$PYPID" 2>/dev/null || true
  exit 1
fi

APP_DIR="$DIST_DIR/${APP_NAME}.app"
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR/Contents/MacOS"
mkdir -p "$APP_DIR/Contents/Resources"

# App icon: SVG -> PNG (qlmanage) -> iconset (sips) -> .icns (iconutil)
ICON_SVG="$REPO_ROOT/scripts/macos/copaw-symbol.svg"
ICON_TMP="$DIST_DIR/icon_build"
if [[ -f "$ICON_SVG" ]]; then
  echo "[build_dmg] Building app icon from copaw-symbol.svg..."
  rm -rf "$ICON_TMP"
  mkdir -p "$ICON_TMP"
  (cd "$ICON_TMP" && qlmanage -t -s 1024 -o . "$ICON_SVG" 2>/dev/null)
  SRC_PNG="$ICON_TMP/copaw-symbol.svg.png"
  if [[ -f "$SRC_PNG" ]]; then
    ICONSET="$ICON_TMP/CoPaw.iconset"
    mkdir -p "$ICONSET"
    for size in 16 32 128 256 512; do
      sips -z $size $size "$SRC_PNG" --out "$ICONSET/icon_${size}x${size}.png"
      d=$((size * 2))
      sips -z $d $d "$SRC_PNG" --out "$ICONSET/icon_${size}x${size}@2x.png"
    done
    iconutil -c icns "$ICONSET" -o "$APP_DIR/Contents/Resources/Icon.icns"
    echo "[build_dmg] Icon.icns installed."
  fi
  rm -rf "$ICON_TMP"
fi

cp -R "$PYINSTALLER_OUT/"* "$APP_DIR/Contents/MacOS/"

# PyInstaller bootloader uses Contents/Frameworks as PYTHONHOME; sys.path expects
# base_library.zip etc. directly under Frameworks. Copy _internal contents there.
FRAMEWORKS="$APP_DIR/Contents/Frameworks"
INTERNAL="$APP_DIR/Contents/MacOS/_internal"
mkdir -p "$FRAMEWORKS"
cp -R "$INTERNAL/"* "$FRAMEWORKS/"

cat > "$APP_DIR/Contents/Info.plist" << INFOPLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key>
  <string>CoPaw</string>
  <key>CFBundleIconFile</key>
  <string>Icon</string>
  <key>CFBundleIdentifier</key>
  <string>ai.agentscope.copaw</string>
  <key>CFBundleName</key>
  <string>CoPaw</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>${VERSION}</string>
  <key>CFBundleVersion</key>
  <string>${VERSION}</string>
  <key>LSMinimumSystemVersion</key>
  <string>${MACOSX_DEPLOYMENT_TARGET}</string>
  <key>NSHighResolutionCapable</key>
  <true/>
</dict>
</plist>
INFOPLIST

rm -rf "$PYINSTALLER_OUT"

DMG_PATH="$DIST_DIR/${DMG_NAME}.dmg"
if command -v create-dmg &>/dev/null; then
  rm -f "$DMG_PATH"
  create-dmg --volname "CoPaw $VERSION" --window-pos 200 120 --window-size 600 400 \
    --icon-size 100 --app-drop-link 450 200 --no-internet-enable "$DMG_PATH" "$APP_DIR"
else
  TMP_DMG="$DIST_DIR/tmp_${DMG_NAME}.dmg"
  rm -f "$TMP_DMG" "$DMG_PATH"
  hdiutil create -volname "CoPaw $VERSION" -srcfolder "$APP_DIR" -ov -format UDZO "$TMP_DMG"
  mv "$TMP_DMG" "$DMG_PATH"
fi

echo "[build_dmg] Done. App: $APP_DIR  DMG: $DMG_PATH"
echo "  Double-click CoPaw to open the Console in a window."
