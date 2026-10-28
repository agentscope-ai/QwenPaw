#!/usr/bin/env bash
# Build QwenPaw Desktop for Linux: a .deb and an .AppImage from the same
# Tauri shell used on Windows/macOS (bundled Python runtime + PyInstaller
# backend + Node runtime, no Docker).
#
# Usage:
#   bash scripts/pack-tauri/build_linux_pyinstaller.sh
#
# Output:
#   console/src-tauri/target/release/bundle/deb/*.deb
#   console/src-tauri/target/release/bundle/appimage/*.AppImage
#   dist/QwenPaw-Tauri-<version>-linux-<arch>.deb
#   dist/QwenPaw-Tauri-<version>-linux-<arch>.AppImage
#
# Prerequisites (Ubuntu/Debian):
#   sudo apt-get install -y build-essential curl file patchelf libfuse2 \
#     libgtk-3-dev libsoup-3.0-dev librsvg2-dev libayatana-appindicator3-dev \
#     libwebkit2gtk-4.1-dev
#   Rust (rustup) and Node.js >= 22 must be on PATH; Python 3.11-3.13 is used
#   only to bootstrap the bundled runtime.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

VERSION=$(sed -n 's/^__version__[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' src/qwenpaw/__version__.py)
if [ -z "${VERSION}" ]; then
  echo "ERROR: could not read __version__ from src/qwenpaw/__version__.py"
  exit 1
fi
ARCH="$(uname -m)"

echo "========================================="
echo "QwenPaw Desktop - Linux build"
echo "========================================="
echo "Version:    ${VERSION}"
echo "Arch:       ${ARCH}"
echo "Repository: ${REPO_ROOT}"
echo ""

# ---------------------------------------------------------------- prerequisites
echo "== Checking prerequisites =="
missing=()
for tool in npm node rustc cargo python3; do
  if command -v "${tool}" >/dev/null 2>&1; then
    echo "  [OK] ${tool}"
  else
    echo "  [MISSING] ${tool}"
    missing+=("${tool}")
  fi
done

# The bootstrap interpreter only runs this build; the runtime that ships inside
# the app is staged separately and must stay inside the supported series.
# A newer host Python (3.14+) is fine: staging falls back to 3.13 on its own.
if command -v python3 >/dev/null 2>&1; then
  HOST_PY="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  case "${HOST_PY}" in
    3.11|3.12|3.13) echo "  [OK] python3 ${HOST_PY} (used as the bootstrap interpreter)" ;;
    *) echo "  [INFO] python3 ${HOST_PY} is outside 3.11-3.13; the bundled runtime will be staged as 3.13" ;;
  esac
fi

if ! pkg-config --exists webkit2gtk-4.1 2>/dev/null; then
  echo "  [MISSING] webkit2gtk-4.1 (pkg-config)"
  missing+=("libwebkit2gtk-4.1-dev")
fi

if [ ${#missing[@]} -gt 0 ]; then
  echo ""
  echo "Missing prerequisites: ${missing[*]}"
  echo ""
  echo "Install the system packages:"
  echo "  sudo apt-get install -y build-essential curl file patchelf libfuse2 pkgconf \\"
  echo "    libgtk-3-dev libsoup-3.0-dev librsvg2-dev \\"
  echo "    libayatana-appindicator3-dev libwebkit2gtk-4.1-dev"
  echo ""
  echo "Install Rust and Node.js >= 22 if those are listed above."
  exit 1
fi
echo ""

# ------------------------------------------------------- 1) console + version sync
if [ "${QWENPAW_SKIP_BACKEND_BUILD:-0}" = "1" ]; then
  echo "== Steps 1-2 skipped (QWENPAW_SKIP_BACKEND_BUILD=1); reusing console/src-tauri/binaries =="
else
echo "== Step 1: console assets + Tauri version override =="
cd console
npm ci
node ../scripts/pack-tauri/sync_tauri_version.mjs
npm run build:prod
cd ..
echo "Console assets built"
echo ""

# ------------------------------------------------------------- 2) PyInstaller backend
# This also stages binaries/python-runtime and binaries/node-runtime, which the
# Tauri bundle declares as resources.
echo "== Step 2: PyInstaller backend + bundled runtimes =="
bash scripts/pack-tauri/build_pyinstaller.sh
echo ""
fi

# ------------------------------------------------------------------- 3) Tauri bundles
# Tauri merges into an existing AppDir instead of recreating it, so leftovers
# from an earlier product name (or an earlier failed run) stay behind and can
# break the next bundling step. Always start from clean bundle directories.
rm -rf "${REPO_ROOT}/console/src-tauri/target/release/bundle/deb" \
       "${REPO_ROOT}/console/src-tauri/target/release/bundle/appimage"

echo "== Step 3: Tauri bundles (deb + AppImage) =="
cd console
# CI/containers usually have no FUSE; this lets the AppImage bundler extract
# and run itself without mounting.
set +e
APPIMAGE_EXTRACT_AND_RUN=1 npm exec -- tauri build \
  --config src-tauri/tauri.version.conf.json \
  --bundles deb,appimage
TAURI_STATUS=$?
set -e
cd ..
echo ""

# ------------------------------------------------------- 3b) AppImage fallback
# linuxdeploy walks every ELF file in the AppDir and shells out to `ldd` for
# each one. With a bundled Python runtime that is thousands of files, and a
# single unresolved name aborts the whole bundling step. Our AppDir already
# ships every dependency it needs, so dependency inference adds nothing: pack
# the tree with appimagetool when linuxdeploy fails.
APPDIR_ROOT="${REPO_ROOT}/console/src-tauri/target/release/bundle/appimage"
APPDIR="$(ls -d "${APPDIR_ROOT}"/*.AppDir 2>/dev/null | head -1 || true)"
APPIMAGE_OUT=""
if [ "${TAURI_STATUS}" -ne 0 ]; then
  if [ -z "${APPDIR}" ] || [ ! -x "${APPDIR}/AppRun" ]; then
    echo "ERROR: bundling failed and no usable AppDir was produced"
    exit "${TAURI_STATUS}"
  fi
  echo "== Step 3b: tauri bundling failed; packing the AppDir with appimagetool =="

  APPDIR_NAME="$(basename "${APPDIR}" .AppDir)"
  # Tauri emits the resource payload twice under usr/lib (once per product
  # name it knows about). Keep only the one the runtime resolves.
  # The runtime resolves resources under usr/lib/<product name>, and Tauri can
  # emit the payload under two names. Keep one real tree and point the other
  # name at it, so either resolution works and the archive stores it once.
  PRIMARY_LIB=""
  for lib_dir in "${APPDIR}"/usr/lib/*/; do
    [ -d "${lib_dir}" ] || continue
    name="$(basename "${lib_dir}")"
    if [ -d "${lib_dir}binaries" ] && [ "${name}" = "${APPDIR_NAME}" ]; then
      PRIMARY_LIB="${name}"
    fi
  done
  for lib_dir in "${APPDIR}"/usr/lib/*/; do
    [ -d "${lib_dir}" ] || continue
    name="$(basename "${lib_dir}")"
    [ -d "${lib_dir}binaries" ] || continue
    if [ -z "${PRIMARY_LIB}" ]; then
      PRIMARY_LIB="${name}"
      continue
    fi
    if [ "${name}" != "${PRIMARY_LIB}" ]; then
      echo "    deduplicating usr/lib/${name} -> symlink to ${PRIMARY_LIB}"
      rm -rf "${lib_dir}"
      ln -sfn "${PRIMARY_LIB}" "${APPDIR}/usr/lib/${name}"
    fi
  done

  # appimagetool wants the icon named by the desktop entry next to it.
  DESKTOP_FILE="$(ls "${APPDIR}"/usr/share/applications/*.desktop 2>/dev/null | head -1 || true)"
  if [ -n "${DESKTOP_FILE}" ]; then
    ICON_NAME="$(sed -n 's/^Icon=//p' "${DESKTOP_FILE}" | head -1)"
    if [ -n "${ICON_NAME}" ] && [ ! -e "${APPDIR}/${ICON_NAME}.png" ]; then
      SOURCE_PNG="$(ls "${APPDIR}"/*.png 2>/dev/null | head -1 || true)"
      if [ -n "${SOURCE_PNG}" ]; then
        cp -f "${SOURCE_PNG}" "${APPDIR}/${ICON_NAME}.png"
      fi
    fi
    if [ -n "${ICON_NAME}" ] && [ -e "${APPDIR}/${ICON_NAME}.png" ]; then
      ln -sfn "${ICON_NAME}.png" "${APPDIR}/.DirIcon"
    fi
  fi

  TOOL_CACHE="${XDG_CACHE_HOME:-${HOME}/.cache}/qwenpaw-desktop"
  mkdir -p "${TOOL_CACHE}"
  APPIMAGETOOL="${TOOL_CACHE}/appimagetool-x86_64.AppImage"
  if [ ! -x "${APPIMAGETOOL}" ]; then
    echo "    downloading appimagetool"
    curl -fL --retry 3 -o "${APPIMAGETOOL}" \
      https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x "${APPIMAGETOOL}"
  fi

  APPIMAGE_OUT="${APPDIR_ROOT}/${APPDIR_NAME}.AppImage"
  ARCH="$(uname -m)" APPIMAGE_EXTRACT_AND_RUN=1 "${APPIMAGETOOL}" \
    --no-appstream "${APPDIR}" "${APPIMAGE_OUT}"
fi
echo ""

# ---------------------------------------------------------------- 4) collect output
echo "== Step 4: collect artifacts =="
DIST="${DIST:-dist}"
if [[ "${DIST}" != /* ]]; then
  DIST="${REPO_ROOT}/${DIST}"
fi
mkdir -p "${DIST}"

BUNDLE_DIR="${REPO_ROOT}/console/src-tauri/target/release/bundle"
DEB_PATH="$(ls -1 "${BUNDLE_DIR}"/deb/*.deb 2>/dev/null | head -1 || true)"
APPIMAGE_PATH="$(ls -1 "${BUNDLE_DIR}"/appimage/*.AppImage 2>/dev/null | head -1 || true)"

if [ -z "${DEB_PATH}" ]; then
  echo "ERROR: no .deb produced under ${BUNDLE_DIR}/deb"
  exit 1
fi
if [ -z "${APPIMAGE_PATH}" ]; then
  echo "ERROR: no .AppImage produced under ${BUNDLE_DIR}/appimage"
  exit 1
fi

DEB_OUT="${DIST}/QwenPaw-Tauri-${VERSION}-linux-${ARCH}.deb"
APPIMAGE_OUT="${DIST}/QwenPaw-Tauri-${VERSION}-linux-${ARCH}.AppImage"
cp -f "${DEB_PATH}" "${DEB_OUT}"
cp -f "${APPIMAGE_PATH}" "${APPIMAGE_OUT}"
chmod +x "${APPIMAGE_OUT}"

# --------------------------------------------------------------- 5) cleanup
# Tauri stages a full copy of the bundle resources under
# target/release/binaries, and linuxdeploy keeps its working trees under
# target/release/bundle/appimage_deb. Together they are tens of gigabytes of
# pure intermediates that are rebuilt on the next run. Drop them by default;
# set QWENPAW_DESKTOP_KEEP_STAGING=1 to keep them for debugging.
if [ "${QWENPAW_DESKTOP_KEEP_STAGING:-0}" != "1" ]; then
  echo "== Step 5: clean packaging intermediates =="
  BUNDLE_ROOT="${REPO_ROOT}/console/src-tauri/target/release"
  rm -rf \
    "${BUNDLE_ROOT}/binaries" \
    "${BUNDLE_ROOT}/bundle/appimage_deb" \
    "${BUNDLE_ROOT}/bundle/deb" \
    "${BUNDLE_ROOT}/bundle/appimage"
  echo "Removed staged resources and bundle working trees."
  echo "Set QWENPAW_DESKTOP_KEEP_STAGING=1 to keep them."
fi

echo ""
echo "========================================="
echo "Build complete"
echo "========================================="
ls -lh "${DEB_OUT}" "${APPIMAGE_OUT}"
echo ""
echo "Install / run:"
echo "  sudo apt install ./$(basename "${DEB_OUT}")"
echo "  ./$(basename "${APPIMAGE_OUT}")"
