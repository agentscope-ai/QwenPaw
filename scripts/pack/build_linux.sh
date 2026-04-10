#!/usr/bin/env bash
# One-click build: console -> conda-pack -> CoPaw.AppImage. Run from repo root.
# Requires: conda, node/npm (for console), appimagetool (for AppImage)
# 
# Usage:
#   bash ./scripts/pack/build_linux.sh           # Build AppImage
#   DEBUG=1 bash ./scripts/pack/build_linux.sh   # Keep temp files for debugging

set -e
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
PACK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST="${DIST:-dist}"
ARCHIVE="${DIST}/copaw-env.tar.gz"
APP_NAME="CoPaw"
APPDIR="${DIST}/${APP_NAME}.AppDir"

PYTHON_CMD="${PYTHON:-python3}"
echo "== Building wheel (includes console frontend) =="
# Skip wheel_build if dist already has a wheel for current version
VERSION_FILE="${REPO_ROOT}/src/copaw/__version__.py"
CURRENT_VERSION=""
if [[ -f "${VERSION_FILE}" ]]; then
  CURRENT_VERSION="$(
    sed -n 's/^__version__[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' \
      "${VERSION_FILE}" 2>/dev/null
  )"
fi
if [[ -n "${CURRENT_VERSION}" ]]; then
  shopt -s nullglob
  whls=("${REPO_ROOT}/dist/copaw-${CURRENT_VERSION}-"*.whl)
  if [[ ${#whls[@]} -gt 0 ]]; then
    echo "dist/ already has wheel for version ${CURRENT_VERSION}, skipping."
  else
    # Clean up old wheels to avoid confusion
    old_whls=("${REPO_ROOT}/dist/copaw-"*.whl)
    if [[ ${#old_whls[@]} -gt 0 ]]; then
      echo "Removing old wheel files: ${old_whls[*]}"
      rm -f "${old_whls[@]}"
    fi
    bash scripts/wheel_build.sh
  fi
else
  bash scripts/wheel_build.sh
fi

echo "== Building conda-packed env =="
"${PYTHON_CMD}" "${PACK_DIR}/build_common.py" --output "$ARCHIVE" --format tar.gz

echo "== Building AppImage =="
rm -rf "$APPDIR"
mkdir -p "${APPDIR}/usr"

# Unpack conda env into usr/
mkdir -p "${APPDIR}/usr/env"
tar -xzf "$ARCHIVE" -C "${APPDIR}/usr/env" --strip-components=0

# Fix paths for portability
if [[ -x "${APPDIR}/usr/env/bin/conda-unpack" ]]; then
  (cd "${APPDIR}/usr/env" && ./bin/conda-unpack)
fi

# Create AppRun launcher (required for AppImage)
# This is the entry point that AppImage uses
cat > "${APPDIR}/AppRun" << 'LAUNCHER'
#!/usr/bin/env bash
# CoPaw AppImage Launcher
# AppImage sets $APPDIR to the directory containing this script

ENV_DIR="${APPDIR}/usr/env"
LOG="${HOME}/.copaw/desktop.log"
unset PYTHONPATH
export PYTHONHOME="$ENV_DIR"
export COPAW_DESKTOP_APP=1
cd "$HOME" || true

if [ ! -t 2 ]; then
  mkdir -p "$HOME/.copaw"
  { echo "=== $(date) CoPaw starting ==="
    echo "ENV_DIR=$ENV_DIR"
    echo "Python: $ENV_DIR/bin/python (exists=$([ -x "$ENV_DIR/bin/python" ] && echo yes || echo no))"
  } >> "$LOG"
  exec 2>> "$LOG"
  exec 1>> "$LOG"
fi

if [ ! -x "$ENV_DIR/bin/python" ]; then
  echo "ERROR: python not executable at $ENV_DIR/bin/python"
  exit 1
fi

if [ ! -f "$HOME/.copaw/config.json" ]; then
  "$ENV_DIR/bin/python" -u -m copaw init --defaults --accept-security
fi

if [ ! -t 2 ]; then
  echo "Launching python..."
  # Use 'app' instead of 'desktop' to open browser automatically
  "$ENV_DIR/bin/python" -u -m copaw app --no-browser
  EXIT=$?
  if [ $EXIT -ge 128 ]; then
    SIG=$((EXIT - 128))
    echo "Exit code: $EXIT (killed by signal $SIG, e.g. 9=SIGKILL 15=SIGTERM)"
  else
    echo "Exit code: $EXIT"
  fi
  echo "--- Full log: $LOG (scroll up for Python traceback if app exited early) ---"
  exit $EXIT
else
  # Use 'app' instead of 'desktop' to open browser automatically
  exec "$ENV_DIR/bin/python" -u -m copaw app --no-browser
fi
LAUNCHER
chmod +x "${APPDIR}/AppRun"

# Create desktop file
mkdir -p "${APPDIR}/usr/share/applications"
mkdir -p "${APPDIR}/usr/share/icons/hicolor/256x256/apps"
cat > "${APPDIR}/usr/share/applications/${APP_NAME}.desktop" << DESKTOP
[Desktop Entry]
Name=CoPaw
Comment=Your Personal AI Assistant
Exec=AppRun
Icon=${APP_NAME}
Terminal=false
Type=Application
Categories=Network;Chat;X-AI;
Keywords=AI;assistant;chat;llm;copaw;
DESKTOP

# Create icon placeholder (PNG - simplest approach)
# For production, you'd use a proper icon, but this creates a basic structure
ICON_PATH="${PACK_DIR}/assets/icon.png"
if [[ ! -f "${ICON_PATH}" ]]; then
  echo "Warning: icon.png not found at ${PACK_DIR}/assets/"
  # Create a minimal 1x1 PNG as placeholder (won't display nicely but won't error)
  ICON_PATH=$(mktemp)
  trap 'rm -f "${ICON_PATH}"' EXIT
  echo -n -e '\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82' > "${ICON_PATH}"
fi

# Copy icon to multiple standard sizes for better compatibility
for size in 16 32 48 64 128 256; do
  mkdir -p "${APPDIR}/usr/share/icons/hicolor/${size}x${size}/apps"
  cp "${ICON_PATH}" "${APPDIR}/usr/share/icons/hicolor/${size}x${size}/apps/${APP_NAME}.png"
done

# Create desktop file symlink for AppImage root (required by appimagetool)
ln -sf "usr/share/applications/${APP_NAME}.desktop" "${APPDIR}/${APP_NAME}.desktop"
ln -sf "usr/share/icons/hicolor/256x256/apps/${APP_NAME}.png" "${APPDIR}/${APP_NAME}.png"

# Version info
VERSION="${CURRENT_VERSION}"
if [[ -z "${VERSION}" ]]; then
  VERSION="$("${APPDIR}/usr/env/bin/python" -c \
    "from importlib.metadata import version; print(version('copaw'))" 2>/dev/null \
    || echo "0.0.0")"
fi
echo "Building version: ${VERSION}"

# Create usr/version file (optional, useful for debugging)
echo "${VERSION}" > "${APPDIR}/usr/version"

# Check if appimagetool is available
if command -v appimagetool &> /dev/null; then
  echo "== Creating AppImage with appimagetool =="
  appimagetool "${APPDIR}" "${DIST}/CoPaw-${VERSION}-linux-x86_64.AppImage"
  echo "== Built ${DIST}/CoPaw-${VERSION}-linux-x86_64.AppImage =="
else
  echo "== appimagetool not found =="
  echo "To create AppImage, install appimagetool:"
  echo "  wget https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"
  echo "  chmod +x appimagetool-x86_64.AppImage"
  echo ""
  echo "Or use Docker (recommended for consistent builds):"
  echo "  docker run --rm -v \$(pwd):/src -w /src ghcr.io/appimage/continuous/appimagetool-x86_64 ${APPDIR} ${DIST}/CoPaw-${VERSION}-linux-x86_64.AppImage"
  echo ""
  echo "AppDir is ready at: ${APPDIR}"
  echo "You can test it with: cd ${APPDIR} && ./AppRun"
fi

# Cleanup temp files unless DEBUG is set
if [[ -z "${DEBUG}" ]]; then
  echo "== Cleaning up =="
  rm -f "$ARCHIVE"
  # Keep AppDir for now - user may want to test
  # rm -rf "$APPDIR"
else
  echo "== DEBUG mode: keeping temp files =="
fi

echo "== Done =="
