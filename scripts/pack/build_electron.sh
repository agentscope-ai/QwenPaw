#!/bin/bash
# Electron build script for RyPaw Desktop (macOS/Linux)

set -e
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
echo "[build_electron] REPO_ROOT=$REPO_ROOT"

DIST="$REPO_ROOT/dist"
ELECTRON_DIR="$REPO_ROOT/electron"
PYTHON_RUNTIME_DIR="$DIST/python-runtime"

# Clean previous builds
rm -rf "$DIST"
mkdir -p "$DIST"

echo "== Step 1: Building console frontend =="
cd "$REPO_ROOT/console"
npm run build
cd "$REPO_ROOT"

echo "== Step 2: Building Python wheel =="
if [ -f "$REPO_ROOT/scripts/wheel_build.sh" ]; then
  bash "$REPO_ROOT/scripts/wheel_build.sh"
else
  echo "[build_electron] Wheel build script not found, skipping..."
fi

echo "== Step 3: Creating portable Python runtime =="
# For macOS/Linux, we use conda-pack or Python Embedded
python "$REPO_ROOT/scripts/pack/build_common.py" \
  --output "$DIST/rypaw-env.tar.gz" \
  --format tar.gz \
  --cache-wheels

# Extract to python-runtime directory
echo "[build_electron] Extracting Python runtime..."
mkdir -p "$PYTHON_RUNTIME_DIR"

# Extract: macOS uses BSD tar (no --warning flag)
echo "[build_electron] Extracting archive..."
tar -xzf "$DIST/rypaw-env.tar.gz" -C "$PYTHON_RUNTIME_DIR"
echo "[build_electron] Extraction finished (exit code: $?)"

# Verify extraction worked (Python may be at root or in bin/ subdirectory)
PYTHON_EXE=""
if [ -f "$PYTHON_RUNTIME_DIR/python" ]; then
  PYTHON_EXE="$PYTHON_RUNTIME_DIR/python"
elif [ -f "$PYTHON_RUNTIME_DIR/python3" ]; then
  PYTHON_EXE="$PYTHON_RUNTIME_DIR/python3"
elif [ -f "$PYTHON_RUNTIME_DIR/bin/python" ]; then
  PYTHON_EXE="$PYTHON_RUNTIME_DIR/bin/python"
elif [ -f "$PYTHON_RUNTIME_DIR/bin/python3" ]; then
  PYTHON_EXE="$PYTHON_RUNTIME_DIR/bin/python3"
fi

if [ -z "$PYTHON_EXE" ]; then
  echo "[build_electron] ERROR: Python executable not found after extraction"
  echo "[build_electron] Archive contents:"
  tar -tzf "$DIST/rypaw-env.tar.gz" | head -20
  echo ""
  echo "[build_electron] Extracted directory structure:"
  ls -la "$PYTHON_RUNTIME_DIR" | head -20
  exit 1
fi

echo "[build_electron] Python runtime extracted successfully"
echo "[build_electron] Found Python at: $PYTHON_EXE"

# Run conda-unpack to fix paths
CONDA_UNPACK=""
if [ -f "$PYTHON_RUNTIME_DIR/bin/conda-unpack" ]; then
  CONDA_UNPACK="$PYTHON_RUNTIME_DIR/bin/conda-unpack"
elif [ -f "$PYTHON_RUNTIME_DIR/Scripts/conda-unpack.exe" ]; then
  CONDA_UNPACK="$PYTHON_RUNTIME_DIR/Scripts/conda-unpack.exe"
fi

if [ -n "$CONDA_UNPACK" ]; then
  echo "[build_electron] Running conda-unpack to fix hardcoded paths..."
  chmod +x "$CONDA_UNPACK"
  "$CONDA_UNPACK"
  UNPACK_EXIT=$?
  if [ $UNPACK_EXIT -ne 0 ]; then
    echo "[build_electron] ERROR: conda-unpack failed with exit code $UNPACK_EXIT"
    exit 1
  fi
  echo "[build_electron] conda-unpack completed successfully"
else
  echo "[build_electron] WARN: conda-unpack not found, skipping path fixup"
fi

echo "== Step 4: Copying console build =="
CONSOLE_DIST="$REPO_ROOT/console/dist"
CONSOLE_TARGET="$DIST/console"

if [ -d "$CONSOLE_DIST" ]; then
  echo "[build_electron] Found console build at $CONSOLE_DIST"

  # Remove old target if it exists as a file (weird edge case)
  if [ -f "$CONSOLE_TARGET" ]; then
    echo "[build_electron] Removing old file at $CONSOLE_TARGET"
    rm -f "$CONSOLE_TARGET"
  fi

  # Create target directory
  mkdir -p "$CONSOLE_TARGET"

  # Copy contents (using rsync if available for better error handling)
  if command -v rsync >/dev/null 2>&1; then
    rsync -av --delete "$CONSOLE_DIST"/ "$CONSOLE_TARGET/" 2>&1 | tail -5
  else
    # Fallback to cp
    cp -r "$CONSOLE_DIST"/* "$CONSOLE_TARGET/" 2>/dev/null
  fi

  echo "[build_electron] Console build copied successfully"

  # Verify files were copied
  FILE_COUNT=$(find "$CONSOLE_TARGET" -type f | wc -l)
  echo "[build_electron] Copied $FILE_COUNT files to console/"
else
  echo "[build_electron] WARN: Console dist not found at $CONSOLE_DIST"
  echo "[build_electron] You may need to build the console first:"
  echo "[build_electron]   cd console && npm install && npm run build"
  echo "[build_electron] Continuing without console..."
fi

echo "== Step 5: Installing Electron dependencies =="
cd "$ELECTRON_DIR"
npm install

echo "== Step 6: Building Electron application =="
# Set version from __version__.py
VERSION=$(grep '__version__' "$REPO_ROOT/src/rypaw/__version__.py" | sed 's/__version__ = "\(.*\)"/\1/')
echo "[build_electron] Raw rypaw version: $VERSION"

# Convert Python version (e.g., 0.0.7.post1) to semver (e.g., 0.0.7-post1)
# electron-builder requires valid semver format
ELECTRON_VERSION=$(echo "$VERSION" | sed 's/\.post\([0-9]\)/-post\1/')
echo "[build_electron] Electron version: $ELECTRON_VERSION"

# Replace version while preserving the comma
sed -i.bak "s/\"version\": \".*\"/\"version\": \"$ELECTRON_VERSION\"/" "$ELECTRON_DIR/package.json"

# Build for current platform
if [[ "$OSTYPE" == "darwin"* ]]; then
  npm run build:mac

  # Ad-hoc code sign the .app bundle so macOS doesn't kill the renderer process.
  # This doesn't require an Apple Developer account — it just satisfies the
  # system's basic signature check for unsigned apps.
  echo "== Step 7: Ad-hoc signing macOS app =="
  for APP_BUNDLE in "$DIST"/mac*/"RyPaw Desktop.app"; do
    if [ -d "$APP_BUNDLE" ]; then
      echo "[build_electron] Signing: $APP_BUNDLE"
      codesign --force --deep --sign - "$APP_BUNDLE"
      echo "[build_electron] Signed successfully"
    fi
  done
else
  npm run build:linux
fi

cd "$REPO_ROOT"

echo "== Build complete! =="
echo "[build_electron] Output in dist/ directory"
