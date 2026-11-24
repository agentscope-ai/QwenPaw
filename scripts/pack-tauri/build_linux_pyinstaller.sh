#!/usr/bin/env bash
# Build QwenPaw Desktop for Linux: a .deb from the same
# Tauri shell used on Windows/macOS (bundled Python runtime + PyInstaller
# backend + Node runtime, no Docker).
#
# Usage:
#   bash scripts/pack-tauri/build_linux_pyinstaller.sh
#
# Output:
#   console/src-tauri/target/release/bundle/deb/*.deb
#   dist/QwenPaw-Tauri-<version>-linux-<arch>.deb
#
# Prerequisites (Ubuntu/Debian):
#   sudo apt-get install -y build-essential curl file libtbb12 pkgconf \
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
for tool in npm node rustc cargo python3 ar tar gzip; do
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
  echo "  sudo apt-get install -y build-essential curl file libtbb12 pkgconf \\"
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
# Start from a clean bundle directory so collection cannot pick up an old deb.
rm -rf "${REPO_ROOT}/console/src-tauri/target/release/bundle/deb"

echo "== Step 3: Tauri Debian package =="
cd console
npm exec -- tauri build \
  --config src-tauri/tauri.version.conf.json \
  --bundles deb
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

if [ -z "${DEB_PATH}" ]; then
  echo "ERROR: no .deb produced under ${BUNDLE_DIR}/deb"
  exit 1
fi

# Tauri writes SemVer into the deb, where '-' means a package revision.
# Rewrite only the control archive; keep the application payload unchanged.
DEB_CONTROL_DIR="$(mktemp -d)"
trap 'rm -rf "$DEB_CONTROL_DIR"' EXIT
mkdir "${DEB_CONTROL_DIR}/files"
ar p "${DEB_PATH}" control.tar.gz | tar -xz -C "${DEB_CONTROL_DIR}/files"
python3 - "${DEB_CONTROL_DIR}/files/control" "${VERSION}" <<'PY'
import re
import sys
from pathlib import Path

match = re.fullmatch(
    r"(\d+\.\d+\.\d+)(?:(a|b|rc)(\d+))?(?:\.post(\d+))?(?:\.dev(\d+))?",
    sys.argv[2],
)
if not match:
    raise SystemExit(f"Unsupported Python version for deb: {sys.argv[2]}")
version, pre, number, post, dev = match.groups()
if pre:
    version += "~" + {"a": "alpha", "b": "beta", "rc": "rc"}[pre] + "." + number
if post is not None:
    version += "+post." + post
if dev is not None:
    # A release's dev builds must also sort before its first alpha.
    version += ("~~dev." if pre is None and post is None else "~dev.") + dev
control = Path(sys.argv[1])
text, count = re.subn(r"(?m)^Version: .+$", f"Version: {version}", control.read_text())
if count != 1:
    raise SystemExit("Expected exactly one Version field in the deb control file")
control.write_text(text)
print(f"Debian package version: {version}")
PY
tar --owner=0 --group=0 -czf "${DEB_CONTROL_DIR}/control.tar.gz" \
  -C "${DEB_CONTROL_DIR}/files" .
ar r "${DEB_PATH}" "${DEB_CONTROL_DIR}/control.tar.gz"
rm -rf "${DEB_CONTROL_DIR}"
trap - EXIT

DEB_OUT="${DIST}/QwenPaw-Tauri-${VERSION}-linux-${ARCH}.deb"
cp -f "${DEB_PATH}" "${DEB_OUT}"

# --------------------------------------------------------------- 5) cleanup
# Drop Tauri's staged resource copies after collecting the package.
# Set QWENPAW_DESKTOP_KEEP_STAGING=1 to keep them for debugging.
if [ "${QWENPAW_DESKTOP_KEEP_STAGING:-0}" != "1" ]; then
  echo "== Step 5: clean packaging intermediates =="
  BUNDLE_ROOT="${REPO_ROOT}/console/src-tauri/target/release"
  rm -rf \
    "${BUNDLE_ROOT}/binaries" \
    "${BUNDLE_ROOT}/bundle/deb"
  echo "Removed staged resources and bundle working trees."
  echo "Set QWENPAW_DESKTOP_KEEP_STAGING=1 to keep them."
fi

echo ""
echo "========================================="
echo "Build complete"
echo "========================================="
ls -lh "${DEB_OUT}"
echo ""
echo "Install / run:"
echo "  sudo apt install ./$(basename "${DEB_OUT}")"
echo "  qwenpaw-desktop"
