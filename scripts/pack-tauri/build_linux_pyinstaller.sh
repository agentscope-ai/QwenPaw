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

if ! pkg-config --exists webkit2gtk-4.1 2>/dev/null; then
  echo "  [MISSING] webkit2gtk-4.1 (pkg-config)"
  missing+=("libwebkit2gtk-4.1-dev")
fi

if [ ${#missing[@]} -gt 0 ]; then
  echo ""
  echo "Missing prerequisites: ${missing[*]}"
  echo ""
  echo "Install the system packages:"
  echo "  sudo apt-get install -y build-essential curl file patchelf libfuse2 \\"
  echo "    libgtk-3-dev libsoup-3.0-dev librsvg2-dev \\"
  echo "    libayatana-appindicator3-dev libwebkit2gtk-4.1-dev"
  echo ""
  echo "Install Rust and Node.js >= 22 if those are listed above."
  exit 1
fi
echo ""

# ------------------------------------------------------- 1) console + version sync
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

# ------------------------------------------------------------------- 3) Tauri bundles
echo "== Step 3: Tauri bundles (deb + AppImage) =="
cd console
# CI/containers usually have no FUSE; this lets the AppImage bundler extract
# and run itself without mounting.
APPIMAGE_EXTRACT_AND_RUN=1 npm exec -- tauri build \
  --config src-tauri/tauri.version.conf.json \
  --bundles deb,appimage
cd ..
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

echo ""
echo "========================================="
echo "Build complete"
echo "========================================="
ls -lh "${DEB_OUT}" "${APPIMAGE_OUT}"
echo ""
echo "Install / run:"
echo "  sudo apt install ./$(basename "${DEB_OUT}")"
echo "  ./$(basename "${APPIMAGE_OUT}")"
