#!/usr/bin/env bash
# =============================================================================
# CoPaw Desktop Build Script — Intel x86_64 (macOS)
# =============================================================================
# Usage:
#   ./build-x86.sh                  # Full build: frontend + sidecar + app + dmg
#   ./build-x86.sh --skip-frontend  # Skip frontend build
#   ./build-x86.sh --skip-sidecar   # Skip sidecar (PyInstaller) build
#   ./build-x86.sh --no-dmg         # Build app only, skip DMG creation
#
# Isolation notes:
#   • PyInstaller intermediate files → desktop/pyinstaller/build-x86 / dist-x86
#     (never touches build/ or dist/ used by the arm64 build)
#   • _internal runtime dir         → src-tauri/binaries/_internal-x86
#     (arm64 _internal is left untouched)
#   • Rust build artifacts          → src-tauri/target/x86_64-apple-darwin/
#     (cargo --target isolates automatically)
#   • DMG output                    → dist/CoPaw-x86_64.dmg
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"

# ── Color helpers ─────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYAN}▶ $*${NC}"; }
success() { echo -e "${GREEN}✔ $*${NC}"; }
warn()    { echo -e "${YELLOW}⚠ $*${NC}"; }
error()   { echo -e "${RED}✘ $*${NC}"; exit 1; }
step()    { echo; echo -e "${CYAN}══════════════════════════════════════════${NC}"; echo -e "${CYAN}  $*${NC}"; echo -e "${CYAN}══════════════════════════════════════════${NC}"; }

# ── Parse args ────────────────────────────────────────────────────────────────
SKIP_FRONTEND=false
SKIP_SIDECAR=false
NO_DMG=false

for arg in "$@"; do
  case "$arg" in
    --skip-frontend) SKIP_FRONTEND=true ;;
    --skip-sidecar)  SKIP_SIDECAR=true  ;;
    --no-dmg)        NO_DMG=true        ;;
    *) error "Unknown option: $arg" ;;
  esac
done

# ── Architecture: x86_64 ──────────────────────────────────────────────────────
TARGET="x86_64-apple-darwin"
info "Building for x86_64 (x86_64-apple-darwin)"

# ── Isolated paths ────────────────────────────────────────────────────────────
SPEC_DIR="$PROJECT_ROOT/desktop/pyinstaller"
# PyInstaller outputs are redirected to -x86 subdirs to avoid colliding with
# the arm64 build/ and dist/ directories that build.sh produces.
X86_BUILD_DIR="$SPEC_DIR/build-x86"
X86_DIST_DIR="$SPEC_DIR/dist-x86"
# _internal-x86 sits next to _internal so arm64 runtime is never overwritten.
BINARIES_DIR="$PROJECT_ROOT/src-tauri/binaries"
X86_INTERNAL="$BINARIES_DIR/_internal-x86"
# Rust produces target/x86_64-apple-darwin/ automatically — no extra action needed.
APP_PATH="$PROJECT_ROOT/src-tauri/target/x86_64-apple-darwin/release/bundle/macos/CoPaw.app"

sync_sidecar_binaries() {
  local src="$1"
  local dst_dir="$2"
  mkdir -p "$dst_dir"
  local dst="$dst_dir/copaw-backend-$TARGET"
  cp "$src" "$dst"
  chmod +x "$dst"
  success "Sidecar → src-tauri/binaries/copaw-backend-$TARGET"
}

# ── Locate x86_64 Python ──────────────────────────────────────────────────────
# Homebrew on Apple Silicon lives in /opt/homebrew (arm64 only).
# x86_64 Python installations (installed natively or via Rosetta) live under
# /usr/local — the traditional x86_64 prefix on macOS.
X86_PYTHON_CANDIDATES=(
  "/usr/local/bin/python3.11"
  "/usr/local/bin/python3.12"
  "/usr/local/bin/python3.13"
  "/usr/local/bin/python3"
)

X86_SYSTEM_PYTHON=""
for candidate in "${X86_PYTHON_CANDIDATES[@]}"; do
  if [ -f "$candidate" ]; then
    arch_tag="$(file "$candidate" | grep -o 'x86_64\|arm64' | head -1)"
    if [ "$arch_tag" = "x86_64" ]; then
      X86_SYSTEM_PYTHON="$candidate"
      break
    fi
  fi
done

if [ -z "$X86_SYSTEM_PYTHON" ]; then
  error "No x86_64 Python found under /usr/local/bin. Please install an Intel Python first."
fi

if [ -f "$PROJECT_ROOT/.venv-x86/bin/python" ]; then
  PYTHON="$PROJECT_ROOT/.venv-x86/bin/python"
  info "Using x86_64 venv: $PYTHON"
else
  warn ".venv-x86 not found, creating from x86_64 Python ($X86_SYSTEM_PYTHON)..."
  "$X86_SYSTEM_PYTHON" -m venv "$PROJECT_ROOT/.venv-x86"
  PYTHON="$PROJECT_ROOT/.venv-x86/bin/python"
  "$PYTHON" -m pip install -e "$PROJECT_ROOT[dev]" -q
  info "Created x86_64 venv: $PYTHON"
fi

# Ensure PyInstaller is installed in the chosen Python env
if ! "$PYTHON" -m PyInstaller --version &>/dev/null; then
  info "Installing PyInstaller into x86_64 Python env..."
  "$PYTHON" -m pip install pyinstaller -q
fi

# Verify Python is actually x86_64
PYTHON_ARCH="$(file "$PYTHON" | grep -o 'arm64\|x86_64' | head -1)"
if [ "$PYTHON_ARCH" != "x86_64" ]; then
  error "Python ($PYTHON) is $PYTHON_ARCH — sidecar will NOT be x86_64. Aborting."
else
  info "Python arch: x86_64 ✔"
fi

# ── Print build info ──────────────────────────────────────────────────────────
echo
echo -e "${CYAN}╔══════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║      CoPaw Desktop Build (x86_64)        ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════╝${NC}"
echo "  Platform : $(uname -s) $(uname -m) → $TARGET"
echo "  Python   : $PYTHON ($PYTHON_ARCH)"
echo "  Skips    : frontend=$SKIP_FRONTEND  sidecar=$SKIP_SIDECAR  dmg=$NO_DMG"
echo "  Isolated :"
echo "    PyInstaller build → $X86_BUILD_DIR"
echo "    PyInstaller dist  → $X86_DIST_DIR"
echo "    _internal         → $X86_INTERNAL"
echo "    Rust artifacts    → src-tauri/target/x86_64-apple-darwin/"

# ── Step 1: Frontend ──────────────────────────────────────────────────────────
if [ "$SKIP_FRONTEND" = false ]; then
  step "Step 1/4  Frontend (React)"
  CONSOLE_DIR="$PROJECT_ROOT/console"
  [ -d "$CONSOLE_DIR" ] || error "console/ directory not found"
  info "npm ci..."
  npm ci --prefix "$CONSOLE_DIR" --silent
  info "npm run build..."
  npm run build --prefix "$CONSOLE_DIR"

  # Copy loading.html to dist so Tauri can serve it in release mode
  LOADING_HTML_SRC="$PROJECT_ROOT/src-tauri/loading.html"
  LOADING_HTML_DST="$CONSOLE_DIR/dist/loading.html"
  if [ -f "$LOADING_HTML_SRC" ]; then
    cp "$LOADING_HTML_SRC" "$LOADING_HTML_DST"
    success "Copied loading.html → console/dist/"
  else
    warn "loading.html not found at $LOADING_HTML_SRC"
  fi

  success "Frontend built → console/dist"
else
  warn "Step 1/4  Skipping frontend build"
  [ -d "$PROJECT_ROOT/console/dist" ] || error "console/dist not found. Run without --skip-frontend first."
  # Ensure loading.html is present even when skipping frontend build
  LOADING_HTML_SRC="$PROJECT_ROOT/src-tauri/loading.html"
  LOADING_HTML_DST="$PROJECT_ROOT/console/dist/loading.html"
  if [ -f "$LOADING_HTML_SRC" ] && [ ! -f "$LOADING_HTML_DST" ]; then
    cp "$LOADING_HTML_SRC" "$LOADING_HTML_DST"
    info "Copied loading.html → console/dist/ (was missing)"
  fi
fi

# ── Step 2: Python Sidecar (PyInstaller) ──────────────────────────────────────
if [ "$SKIP_SIDECAR" = false ]; then
  step "Step 2/4  Python Sidecar (PyInstaller x86_64)"
  SPEC_FILE="$SPEC_DIR/CoPawBackend.spec"
  [ -f "$SPEC_FILE" ] || error "Spec file not found: $SPEC_FILE"

  # Create isolated output directories so arm64 build/ and dist/ are untouched.
  mkdir -p "$X86_BUILD_DIR" "$X86_DIST_DIR"

  info "Running PyInstaller (this takes a few minutes)..."
  # --workpath and --distpath redirect ALL intermediate and output files into
  # the x86-specific directories; the spec file itself is not modified.
  (cd "$SPEC_DIR" && "$PYTHON" -m PyInstaller \
    --clean --noconfirm \
    --workpath "$X86_BUILD_DIR" \
    --distpath "$X86_DIST_DIR" \
    CoPawBackend.spec)

  SIDECAR_SRC="$X86_DIST_DIR/copaw-backend/copaw-backend"
  [ -f "$SIDECAR_SRC" ] || error "Sidecar binary not found at $SIDECAR_SRC"
  SIDECAR_INTERNAL="$X86_DIST_DIR/copaw-backend/_internal"
  [ -d "$SIDECAR_INTERNAL" ] || error "Sidecar _internal dir not found at $SIDECAR_INTERNAL"

  # Verify the produced binary is actually x86_64
  SIDECAR_ARCH="$(file "$SIDECAR_SRC" | grep -o 'x86_64\|arm64' | head -1)"
  if [ "$SIDECAR_ARCH" != "x86_64" ]; then
    error "Produced sidecar is $SIDECAR_ARCH, not x86_64. Check that .venv-x86 uses an Intel Python."
  fi
  success "Sidecar arch verified: x86_64 ✔"

  # Pre-compile Python bytecode to speed up first startup
  info "Pre-compiling Python bytecode..."
  "$PYTHON" -m compileall -q -j 0 "$SIDECAR_INTERNAL" 2>/dev/null || true
  success "Bytecode pre-compilation done"

  sync_sidecar_binaries "$SIDECAR_SRC" "$BINARIES_DIR"

  # Copy _internal to isolated x86-specific directory
  rm -rf "$X86_INTERNAL"
  cp -R "$SIDECAR_INTERNAL" "$X86_INTERNAL"

  # Write sidecar version marker
  SIDE_VERSION_FILE="$X86_INTERNAL/.copaw_sidecar_version"
  SIDE_VERSION_CONTENT="$(jq -r '.version' "$PROJECT_ROOT/src-tauri/tauri.conf.json" 2>/dev/null || echo "unknown")-x86_64-$(shasum -a 256 "$SIDECAR_SRC" | cut -c1-16)"
  echo "$SIDE_VERSION_CONTENT" > "$SIDE_VERSION_FILE"
  info "Wrote sidecar version marker: $SIDE_VERSION_CONTENT"

  success "Sidecar runtime dir → src-tauri/binaries/_internal-x86"

  # Ensure loading.html is in _internal-x86/copaw/console/
  LOADING_HTML_SRC="$PROJECT_ROOT/src-tauri/loading.html"
  SIDECAR_CONSOLE_LOADING="$X86_INTERNAL/copaw/console/loading.html"
  if [ -f "$LOADING_HTML_SRC" ] && [ -d "$X86_INTERNAL/copaw/console" ]; then
    cp "$LOADING_HTML_SRC" "$SIDECAR_CONSOLE_LOADING"
    info "Copied loading.html → _internal-x86/copaw/console/"
  fi
else
  warn "Step 2/4  Skipping sidecar build"
  SIDECAR_DST="$BINARIES_DIR/copaw-backend-$TARGET"
  [ -f "$SIDECAR_DST" ] || error "Sidecar binary not found at $SIDECAR_DST. Run without --skip-sidecar first."
  [ -d "$X86_INTERNAL" ] || error "_internal-x86 not found. Run without --skip-sidecar first."
  # Ensure loading.html is up to date
  LOADING_HTML_SRC="$PROJECT_ROOT/src-tauri/loading.html"
  SIDECAR_CONSOLE_LOADING="$X86_INTERNAL/copaw/console/loading.html"
  if [ -f "$LOADING_HTML_SRC" ] && [ -d "$X86_INTERNAL/copaw/console" ]; then
    if [ ! -f "$SIDECAR_CONSOLE_LOADING" ] || [ "$LOADING_HTML_SRC" -nt "$SIDECAR_CONSOLE_LOADING" ]; then
      cp "$LOADING_HTML_SRC" "$SIDECAR_CONSOLE_LOADING"
      info "Copied loading.html → _internal-x86/copaw/console/"
    fi
  fi
fi

# ── Step 3: Tauri App ─────────────────────────────────────────────────────────
step "Step 3/4  Tauri App (cargo build x86_64)"

# Add x86_64 Rust target if not already installed
if ! rustup target list --installed | grep -q "x86_64-apple-darwin"; then
  info "Adding Rust target x86_64-apple-darwin..."
  rustup target add x86_64-apple-darwin
fi

# Force recompile if loading.html was updated
MAIN_RS="$PROJECT_ROOT/src-tauri/src/main.rs"
TAURI_BIN="$PROJECT_ROOT/src-tauri/target/x86_64-apple-darwin/release/copaw"
LOADING_IN_DIST="$PROJECT_ROOT/console/dist/loading.html"
if [ -f "$LOADING_IN_DIST" ] && [ -f "$TAURI_BIN" ] && [ "$LOADING_IN_DIST" -nt "$TAURI_BIN" ]; then
  touch "$MAIN_RS"
  info "Touched main.rs to force Tauri recompile (loading.html updated)"
fi

# Source cargo env if exists
if [ -f "$HOME/.cargo/env" ]; then
  # shellcheck disable=SC1090
  . "$HOME/.cargo/env"
fi

if ! type rustc &>/dev/null; then
  error "Rust not installed. Visit https://rustup.rs"
fi
if ! type cargo &>/dev/null; then
  error "cargo not found"
fi

# Before running tauri build, temporarily copy _internal-x86 to _internal
# so Tauri bundles the correct x86_64 sidecar runtime into the app.
# The original _internal (arm64) is backed up and restored afterward.
ARM64_INTERNAL="$BINARIES_DIR/_internal"
ARM64_INTERNAL_BAK="$BINARIES_DIR/_internal.arm64-bak"

if [ -d "$ARM64_INTERNAL" ]; then
  info "Backing up arm64 _internal..."
  rm -rf "$ARM64_INTERNAL_BAK"
  cp -R "$ARM64_INTERNAL" "$ARM64_INTERNAL_BAK"
fi

info "Swapping _internal → _internal-x86 for Tauri bundling..."
rm -rf "$ARM64_INTERNAL"
cp -R "$X86_INTERNAL" "$ARM64_INTERNAL"

restore_internal() {
  if [ -d "$ARM64_INTERNAL_BAK" ]; then
    info "Restoring arm64 _internal..."
    rm -rf "$ARM64_INTERNAL"
    mv "$ARM64_INTERNAL_BAK" "$ARM64_INTERNAL"
  fi
}
# Ensure arm64 _internal is restored even if the build fails
trap restore_internal EXIT

info "cargo tauri build --target x86_64-apple-darwin --bundles app..."
(cd "$PROJECT_ROOT" && cargo tauri build --target x86_64-apple-darwin --bundles app)

[ -d "$APP_PATH" ] || error "CoPaw.app not found after build at $APP_PATH"
success "App → $APP_PATH"

# Restore arm64 _internal immediately after tauri build
restore_internal
trap - EXIT  # Clear trap since we already restored

# ── Bundle x86_64 _internal into the app ──────────────────────────────────────
# Re-apply the same _internal layout as build.sh: put it under Contents/
# (not MacOS/) so codesign does not scan non-Mach-O files.
if [ -d "$X86_INTERNAL" ]; then
  rm -rf "$APP_PATH/Contents/_internal"
  cp -R "$X86_INTERNAL" "$APP_PATH/Contents/_internal"

  rm -f "$APP_PATH/Contents/MacOS/_internal"
  ln -s "../_internal" "$APP_PATH/Contents/MacOS/_internal"
  success "Bundled x86_64 sidecar runtime → CoPaw.app/Contents/_internal"

  # PyInstaller's bootloader resolves stdlib from Contents/Frameworks/
  FRAMEWORKS_LINK="$APP_PATH/Contents/Frameworks"
  rm -rf "$FRAMEWORKS_LINK"
  ln -s "_internal" "$FRAMEWORKS_LINK"
  success "Symlinked Contents/Frameworks → _internal"
fi

# Verify sidecar inside app matches x86_64 source binary
APP_SIDECAR="$APP_PATH/Contents/MacOS/copaw-backend"
SRC_SIDECAR="$BINARIES_DIR/copaw-backend-$TARGET"
if [ -f "$APP_SIDECAR" ] && [ -f "$SRC_SIDECAR" ]; then
  APP_SHA="$(shasum -a 256 "$APP_SIDECAR" | awk '{print $1}')"
  SRC_SHA="$(shasum -a 256 "$SRC_SIDECAR" | awk '{print $1}')"
  if [ "$APP_SHA" != "$SRC_SHA" ]; then
    error "Sidecar hash mismatch: app=$APP_SHA src=$SRC_SHA (stale sidecar detected)"
  fi
  success "Sidecar hash verified: $APP_SHA"
fi

# ── Code Signing ──────────────────────────────────────────────────────────────
step "Code Signing (x86_64)"

ENTITLEMENTS_FILE="$PROJECT_ROOT/desktop/entitlements.plist"
if [ ! -f "$ENTITLEMENTS_FILE" ]; then
  warn "Entitlements file not found at $ENTITLEMENTS_FILE, using default signing"
  ENTITLEMENTS_FILE=""
fi

sign_binary() {
  local binary="$1"
  local opts="--force --sign - --timestamp=none"
  if [ -n "$ENTITLEMENTS_FILE" ]; then
    opts="$opts --entitlements \"$ENTITLEMENTS_FILE\""
  fi
  eval codesign $opts \"\$binary\" 2>/dev/null || true
}

info "Signing dylibs and shared libraries..."
find "$APP_PATH/Contents/_internal" -type f \( -name "*.dylib" -o -name "*.so" \) -print0 2>/dev/null | \
  sort -z -r | while IFS= read -r -d '' lib; do
    sign_binary "$lib"
done
success "Signed all embedded libraries"

info "Signing sidecar binary..."
sign_binary "$APP_PATH/Contents/MacOS/copaw-backend"
success "Signed sidecar"

info "Signing main binary..."
TMP_COPAW="/tmp/copaw_sign_x86_$$"
cp "$APP_PATH/Contents/MacOS/copaw" "$TMP_COPAW"
codesign --force --sign - --timestamp=none \
  ${ENTITLEMENTS_FILE:+--entitlements "$ENTITLEMENTS_FILE"} \
  "$TMP_COPAW" 2>/dev/null || true
cp "$TMP_COPAW" "$APP_PATH/Contents/MacOS/copaw"
chmod +x "$APP_PATH/Contents/MacOS/copaw"
rm -f "$TMP_COPAW"
success "Signed main binary"

INFO_PLIST="$APP_PATH/Contents/Info.plist"
plutil -remove CSResourcesFileMapped "$INFO_PLIST" 2>/dev/null || true

info "Signing app bundle..."
codesign --force --sign - --timestamp=none \
  ${ENTITLEMENTS_FILE:+--entitlements "$ENTITLEMENTS_FILE"} \
  "$APP_PATH" 2>&1 || true

if codesign --verify --deep --strict "$APP_PATH" 2>/dev/null; then
  success "App bundle signed and verified"
else
  warn "App bundle signature verification had issues, but continuing"
fi

# ── Step 4: DMG ───────────────────────────────────────────────────────────────
if [ "$NO_DMG" = false ]; then
  step "Step 4/4  DMG Installer (hdiutil)"
  mkdir -p "$PROJECT_ROOT/dist"
  DMG_NAME="CoPaw-x86_64.dmg"
  DMG_PATH="$PROJECT_ROOT/dist/$DMG_NAME"
  TEMP_DMG_PATH="$PROJECT_ROOT/dist/CoPaw-x86_64-tmp.dmg"
  STAGING_DIR="$(mktemp -d "$PROJECT_ROOT/dist/dmg-staging-x86.XXXXXX")"
  VOLUME_NAME="CoPaw Installer"
  DMG_BG_NAME="dmg-background.png"
  DMG_BG_SRC="$PROJECT_ROOT/src-tauri/$DMG_BG_NAME"
  VOLUME_ICON_SRC="$PROJECT_ROOT/src-tauri/icons/icon.icns"

  [ -f "$DMG_PATH" ] && rm -f "$DMG_PATH"
  [ -f "$TEMP_DMG_PATH" ] && rm -f "$TEMP_DMG_PATH"
  rm -rf "$STAGING_DIR"
  mkdir -p "$STAGING_DIR"

  APP_BASENAME="$(basename "$APP_PATH")"
  APP_NAME="${APP_BASENAME%.app}"

  info "Preparing DMG staging folder..."
  cp -R "$APP_PATH" "$STAGING_DIR/$APP_BASENAME"
  ln -s /Applications "$STAGING_DIR/Applications"
  if [ -f "$VOLUME_ICON_SRC" ]; then
    cp "$VOLUME_ICON_SRC" "$STAGING_DIR/.VolumeIcon.icns"
  fi

  info "Creating writable DMG..."
  hdiutil create \
    -volname "$VOLUME_NAME" \
    -srcfolder "$STAGING_DIR" \
    -ov -format UDRW \
    "$TEMP_DMG_PATH"

  info "Configuring Finder layout..."
  ATTACH_LOG="$(hdiutil attach -readwrite -noverify -noautoopen "$TEMP_DMG_PATH")"
  DEVICE_NAME="$(echo "$ATTACH_LOG" | awk '/^\/dev\/disk/ {print $1; exit}')"
  MOUNT_POINT="$(echo "$ATTACH_LOG" | awk '/\/Volumes\// {print substr($0, index($0, "/Volumes/")); exit}')"
  MOUNT_NAME="$(basename "$MOUNT_POINT")"

  if [ -z "$DEVICE_NAME" ] || [ -z "$MOUNT_NAME" ] || [ ! -d "$MOUNT_POINT" ]; then
    error "Failed to mount temporary DMG for customization"
  fi

  mkdir -p "$MOUNT_POINT/.background"
  if [ -f "$DMG_BG_SRC" ]; then
    cp "$DMG_BG_SRC" "$MOUNT_POINT/.background/$DMG_BG_NAME"
  else
    warn "DMG background image not found at $DMG_BG_SRC"
  fi

  if [ -f "$VOLUME_ICON_SRC" ]; then
    if [ ! -f "$MOUNT_POINT/.VolumeIcon.icns" ]; then
      cp "$VOLUME_ICON_SRC" "$MOUNT_POINT/.VolumeIcon.icns"
    fi
    if command -v SetFile >/dev/null 2>&1; then
      SetFile -a C "$MOUNT_POINT" || true
      SetFile -a V "$MOUNT_POINT/.VolumeIcon.icns" || true
    else
      warn "SetFile not found, skipped custom volume icon flag"
    fi
  else
    warn "Volume icon source not found at $VOLUME_ICON_SRC"
  fi

osascript <<EOF
tell application "Finder"
  tell disk "$MOUNT_NAME"
    open
    set current view of container window to icon view
    set toolbar visible of container window to false
    set statusbar visible of container window to false
    set the bounds of container window to {100, 100, 1300, 900}
    set viewOptions to the icon view options of container window
    set arrangement of viewOptions to not arranged
    set icon size of viewOptions to 128
    set bgAlias to (POSIX file "$MOUNT_POINT/.background/$DMG_BG_NAME") as alias
    set background picture of viewOptions to bgAlias
    if exists item "$APP_BASENAME" then
      set position of item "$APP_BASENAME" to {180, 220}
    end if
    if exists item "Applications" then
      set position of item "Applications" to {980, 220}
    end if
    close
    open
    update without registering applications
    delay 2
  end tell
end tell
EOF

  sync
  hdiutil detach "$DEVICE_NAME"
  hdiutil convert "$TEMP_DMG_PATH" -format UDZO -imagekey zlib-level=9 -o "$DMG_PATH"
  rm -f "$TEMP_DMG_PATH"
  rm -rf "$STAGING_DIR"

  success "DMG → dist/$DMG_NAME"
else
  warn "Step 4/4  Skipping DMG creation"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo
echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║      BUILD COMPLETE (x86_64)             ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
[ -d "$APP_PATH" ]                           && echo -e "  App  : ${GREEN}$APP_PATH${NC}"
[ -f "$PROJECT_ROOT/dist/CoPaw-x86_64.dmg" ] && echo -e "  DMG  : ${GREEN}$PROJECT_ROOT/dist/CoPaw-x86_64.dmg${NC}"
echo
