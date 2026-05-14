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

$UV_BIN = (Get-Command uv -ErrorAction SilentlyContinue).Source
$PYTHON_BIN = Join-Path $REPO_ROOT ".venv\Scripts\python.exe"
if (-not (Test-Path $PYTHON_BIN)) {
    if ($UV_BIN) {
        Write-Host ".venv not found, creating virtual environment with uv" -ForegroundColor Yellow
        & $UV_BIN venv "$REPO_ROOT\.venv"
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to create virtual environment with uv"
        }
    } else {
        Write-Host ".venv not found, using system Python" -ForegroundColor Yellow
        $PYTHON_BIN = (Get-Command python -ErrorAction SilentlyContinue).Source
    }
    if (-not $PYTHON_BIN -or -not (Test-Path $PYTHON_BIN)) {
        Write-Host "ERROR: Python not found in .venv or PATH" -ForegroundColor Red
        Write-Host "Please create virtual environment first: python -m venv .venv"
        exit 1
    }
}

$pythonVersion = & $PYTHON_BIN --version
Write-Host "Python: $pythonVersion" -ForegroundColor Green

function Test-PythonImport {
    param([string]$Statement)
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $PYTHON_BIN -c $Statement *> $null
        return $LASTEXITCODE -eq 0
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

function Assert-LastExit {
    param([string]$Message)
    if ($LASTEXITCODE -ne 0) { throw $Message }
}

function Install-PythonPackages {
    param([string[]]$Packages)
    if ($UV_BIN) {
        & $UV_BIN pip install --python $PYTHON_BIN @Packages
    } else {
        & $PYTHON_BIN -m pip install @Packages
    }
    Assert-LastExit "Failed to install Python packages: $($Packages -join ', ')"
}

function Uninstall-PythonPackage {
    param([string]$Package)
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        if ($UV_BIN) {
            & $UV_BIN pip uninstall --python $PYTHON_BIN -y $Package *> $null
        } else {
            & $PYTHON_BIN -m pip uninstall -y $Package *> $null
        }
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

function Get-RustHostTriple {
    $triple = (& rustc --print host-tuple 2>$null)
    if ($LASTEXITCODE -eq 0 -and $triple) {
        return $triple.Trim()
    }

    $triple = (& rustc --print host-triple 2>$null)
    if ($LASTEXITCODE -eq 0 -and $triple) {
        return $triple.Trim()
    }

    $verbose = (& rustc -Vv 2>$null)
    if ($LASTEXITCODE -eq 0) {
        foreach ($line in $verbose) {
            if ($line -match '^host:\s*(\S+)\s*$') {
                return $Matches[1]
            }
        }
    }

    throw "Failed to determine Rust host target triple"
}

# Install PyInstaller if not present
Write-Host "== Installing PyInstaller ==" -ForegroundColor Yellow
if (Test-PythonImport "import PyInstaller") {
    Write-Host "PyInstaller already installed" -ForegroundColor Green
} else {
    Write-Host "Installing PyInstaller..."
    Install-PythonPackages -Packages @("pyinstaller>=6.0.0")
    Write-Host "PyInstaller installed" -ForegroundColor Green
}

# Install python-dotenv if not present (required by PyInstaller collect_submodules)
if (Test-PythonImport "import dotenv") {
    Write-Host "python-dotenv already installed" -ForegroundColor Green
} else {
    Write-Host "Installing python-dotenv..."
    Install-PythonPackages -Packages @("python-dotenv")
    Write-Host "python-dotenv installed" -ForegroundColor Green
}

Write-Host ""

# Install project dependencies (ensures ALL runtime deps are importable)
Write-Host "== Installing project dependencies ==" -ForegroundColor Yellow
Install-PythonPackages -Packages @("-e", ".[full]")
Write-Host "Project dependencies installed with full extras" -ForegroundColor Green

# Fix agent-client-protocol namespace collision
# PyPI has an empty 'acp' stub that shadows the real package
if (-not (Test-PythonImport "from acp import Agent")) {
    Write-Host "Fixing agent-client-protocol namespace..."
    Uninstall-PythonPackage "acp"
    Install-PythonPackages -Packages @("agent-client-protocol")
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

$TARGET_TRIPLE = Get-RustHostTriple
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
