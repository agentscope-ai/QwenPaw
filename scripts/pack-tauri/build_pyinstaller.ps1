# Build QwenPaw backend with PyInstaller for Tauri sidecar (Windows)
# Creates a standalone onefile executable with embedded Python runtime
#
# Usage:
#   powershell ./scripts/pack-tauri/build_pyinstaller.ps1
#
# Prerequisites:
#   - Python 3.10+ with virtual environment
#   - PyInstaller 6.0+ (will be installed if not present)

param()

$ErrorActionPreference = "Stop"
$REPO_ROOT = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $REPO_ROOT

$DIST = if ($env:DIST) { $env:DIST } else { "dist" }
if (-not [System.IO.Path]::IsPathRooted($DIST)) {
    $DIST = Join-Path $REPO_ROOT $DIST
}
$VERSION_FILE = "src\qwenpaw\__version__.py"

# Extract version
if (Test-Path $VERSION_FILE) {
    $content = Get-Content $VERSION_FILE -Raw
    if ($content -match '__version__\s*=\s*"([^"]+)"') {
        $VERSION = $Matches[1]
    } else {
        throw "Failed to extract version from $VERSION_FILE"
    }
} else {
    throw "Version file not found: $VERSION_FILE"
}

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "QwenPaw PyInstaller Build - Windows" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "Version: $VERSION"
Write-Host "Repository: $REPO_ROOT"
Write-Host ""

# Check prerequisites
Write-Host "== Checking prerequisites ==" -ForegroundColor Yellow

$PYTHON_BIN = Join-Path $REPO_ROOT ".venv\Scripts\python.exe"
if (-not (Test-Path $PYTHON_BIN)) {
    Write-Host ".venv not found, using system Python" -ForegroundColor Yellow
    $PYTHON_BIN = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $PYTHON_BIN) {
        Write-Host "ERROR: Python not found in .venv or PATH" -ForegroundColor Red
        Write-Host "Please create virtual environment first: python -m venv .venv"
        exit 1
    }
}

$pythonVersion = & $PYTHON_BIN --version
Write-Host "Python: $pythonVersion" -ForegroundColor Green

# Install PyInstaller if not present
Write-Host "== Installing PyInstaller ==" -ForegroundColor Yellow
try {
    & $PYTHON_BIN -c "import PyInstaller" 2>&1 | Out-Null
    Write-Host "PyInstaller already installed" -ForegroundColor Green
} catch {
    Write-Host "Installing PyInstaller..."
    & $PYTHON_BIN -m pip install "pyinstaller>=6.0.0"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install PyInstaller"
    }
    Write-Host "PyInstaller installed" -ForegroundColor Green
}

Write-Host ""

# Install agent-client-protocol if not present (needed by spec collect_submodules)
try {
    & $PYTHON_BIN -c "from acp import Agent" 2>&1 | Out-Null
} catch {
    Write-Host "Installing agent-client-protocol..."
    # Uninstall wrong 'acp' stub if present (empty package on PyPI)
    & $PYTHON_BIN -m pip uninstall -y acp 2>$null
    & $PYTHON_BIN -m pip install agent-client-protocol
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install agent-client-protocol"
    }
    Write-Host "agent-client-protocol installed" -ForegroundColor Green
}

# Run PyInstaller
Write-Host "== Running PyInstaller ==" -ForegroundColor Yellow
Write-Host "Building standalone executable..."

$SPEC_FILE = Join-Path $REPO_ROOT "scripts\pack-tauri\qwenpaw.spec"
if (-not (Test-Path $SPEC_FILE)) {
    Write-Host "ERROR: Spec file not found at $SPEC_FILE" -ForegroundColor Red
    exit 1
}

& $PYTHON_BIN -m PyInstaller $SPEC_FILE `
    --distpath "${DIST}\pyinstaller" `
    --workpath "${DIST}\pyinstaller-build" `
    --clean `
    --noconfirm

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed"
}

Write-Host "PyInstaller build complete" -ForegroundColor Green
Write-Host ""

# Verify output
$BACKEND_EXE = Join-Path $DIST "pyinstaller\qwenpaw-backend.exe"
if (-not (Test-Path $BACKEND_EXE)) {
    Write-Host "ERROR: Backend executable not found at $BACKEND_EXE" -ForegroundColor Red
    exit 1
}

Write-Host "Backend executable created: $BACKEND_EXE" -ForegroundColor Green

# Get size
$bundleSize = (Get-Item $BACKEND_EXE).Length / 1MB
Write-Host "Bundle size: $([math]::Round($bundleSize, 2)) MB"
Write-Host ""

# Copy to Tauri binaries directory with target triple suffix
Write-Host "== Copying to Tauri binaries directory ==" -ForegroundColor Yellow
$BINARIES_DIR = Join-Path $REPO_ROOT "console\src-tauri\binaries"
New-Item -ItemType Directory -Force -Path $BINARIES_DIR | Out-Null

$TARGET_TRIPLE = & rustc --print host-tuple 2>$null
if (-not $TARGET_TRIPLE) { $TARGET_TRIPLE = "unknown" }
$DEST = Join-Path $BINARIES_DIR "qwenpaw-backend-${TARGET_TRIPLE}.exe"
Copy-Item -Force $BACKEND_EXE $DEST
Write-Host "Copied to: $DEST" -ForegroundColor Green
Write-Host ""

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "PyInstaller Build Complete!" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "Output:"
Write-Host "  Executable: $BACKEND_EXE"
Write-Host "  Tauri sidecar: $DEST"
Write-Host ""
