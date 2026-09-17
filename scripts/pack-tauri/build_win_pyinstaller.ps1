# Build QwenPaw with Tauri for Windows (PyInstaller backend)
# Creates a self-contained desktop app with bundled Python backend
#
# Usage:
#   powershell ./scripts/pack-tauri/build_win_pyinstaller.ps1

param()

$ErrorActionPreference = "Stop"
$REPO_ROOT = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $REPO_ROOT

$DIST = if ($env:DIST) { $env:DIST } else { "dist" }
if (-not [System.IO.Path]::IsPathRooted($DIST)) {
    $DIST = Join-Path $REPO_ROOT $DIST
}
$VERSION_FILE = "src\qwenpaw\__version__.py"

function Invoke-NativeWithRetry {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Description,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command,
        [int]$MaxAttempts = 5,
        [int]$DelaySeconds = 20
    )

    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        Write-Host "$Description (attempt $attempt/$MaxAttempts)..."
        & $Command
        $exitCode = $LASTEXITCODE
        if ($exitCode -eq 0) {
            return
        }

        if ($attempt -eq $MaxAttempts) {
            throw "$Description failed after $MaxAttempts attempts (exit code $exitCode)"
        }

        Write-Host "$Description failed with exit code $exitCode; retrying in $DelaySeconds seconds..." -ForegroundColor Yellow
        Start-Sleep -Seconds $DelaySeconds
    }
}

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
Write-Host "QwenPaw Tauri Build - Windows (PyInstaller)" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "Version: $VERSION"
Write-Host ""

# Step 0: Prerequisites
Write-Host "== Step 0: Checking Prerequisites ==" -ForegroundColor Yellow
$missing = @()

# npm
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Host "  [MISSING] npm" -ForegroundColor Red
    Write-Host "    Install Node.js: https://nodejs.org/" -ForegroundColor Gray
    $missing += "npm"
} else {
    Write-Host "  [OK] npm ($(npm --version))" -ForegroundColor Green
}

# rustc
if (-not (Get-Command rustc -ErrorAction SilentlyContinue)) {
    Write-Host "  [MISSING] rustc (Rust)" -ForegroundColor Red
    Write-Host "    Install: https://rustup.rs" -ForegroundColor Gray
    $missing += "rustc"
} else {
    Write-Host "  [OK] rustc ($(rustc --version))" -ForegroundColor Green
}

# Visual Studio Build Tools (MSVC)
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$hasMsvc = $false
if (Test-Path $vswhere) {
    $vsPath = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath 2>$null
    if ($vsPath) { $hasMsvc = $true }
}
if (-not $hasMsvc) {
    $hostTuple = & rustc --print host-tuple 2>$null
    if ($hostTuple -match "msvc") { $hasMsvc = $true }
}
if (-not $hasMsvc) {
    Write-Host "  [MISSING] Visual Studio Build Tools (C++ workload)" -ForegroundColor Red
    Write-Host "    Install: https://visualstudio.microsoft.com/visual-cpp-build-tools/" -ForegroundColor Gray
    Write-Host "    Required workload: 'Desktop development with C++'" -ForegroundColor Gray
    $missing += "MSVC"
} else {
    Write-Host "  [OK] Visual Studio Build Tools (MSVC)" -ForegroundColor Green
}

# NSIS (makensis)
if (-not (Get-Command makensis -ErrorAction SilentlyContinue)) {
    Write-Host "  [MISSING] makensis (NSIS)" -ForegroundColor Red
    Write-Host "    Install: https://nsis.sourceforge.io/Download" -ForegroundColor Gray
    $missing += "makensis"
} else {
    $nsisInfo = makensis /version 2>$null
    Write-Host "  [OK] makensis (NSIS $nsisInfo)" -ForegroundColor Green
}

if ($missing.Count -gt 0) {
    Write-Host ""
    Write-Host "Missing prerequisites: $($missing -join ', ')" -ForegroundColor Red
    Write-Host "Install the missing tools and re-run this script." -ForegroundColor Red
    exit 1
}
Write-Host ""

# Step 1: Build console static assets
Write-Host "== Step 1: Building Console Static Assets ==" -ForegroundColor Yellow
Set-Location console

Write-Host "Installing frontend dependencies..."
npm ci
if ($LASTEXITCODE -ne 0) {
    throw "npm ci failed"
}

Write-Host "Generating Tauri icons..."
npm exec -- tauri icon ../scripts/pack/assets/icon.svg
if ($LASTEXITCODE -ne 0) {
    throw "Tauri icon generation failed"
}

Write-Host "Syncing Tauri version..."
node ../scripts/pack-tauri/sync_tauri_version.mjs
if ($LASTEXITCODE -ne 0) {
    throw "Tauri version sync failed"
}

Write-Host "Building console frontend..."
npm run build:prod
if ($LASTEXITCODE -ne 0) {
    throw "console frontend build failed"
}

Set-Location $REPO_ROOT
Write-Host "Console static assets built" -ForegroundColor Green
Write-Host ""

# Step 2: Build PyInstaller backend
Write-Host "== Step 2: Building PyInstaller Backend ==" -ForegroundColor Yellow
$PYINSTALLER_SCRIPT = Join-Path $REPO_ROOT "scripts\pack-tauri\build_pyinstaller.ps1"
& $PYINSTALLER_SCRIPT

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed"
}
Write-Host "PyInstaller backend ready" -ForegroundColor Green
Write-Host ""

# Step 2b: Fetch Tauri Rust dependencies
Write-Host "== Step 2b: Fetching Tauri Rust Dependencies ==" -ForegroundColor Yellow
if (-not $env:CARGO_NET_RETRY) {
    $env:CARGO_NET_RETRY = "10"
}
if (-not $env:CARGO_HTTP_MULTIPLEXING) {
    $env:CARGO_HTTP_MULTIPLEXING = "false"
}

$TAURI_MANIFEST = Join-Path $REPO_ROOT "console\src-tauri\Cargo.toml"
Invoke-NativeWithRetry -Description "cargo fetch for Tauri dependencies" -Command {
    cargo fetch --locked --target x86_64-pc-windows-msvc --manifest-path $TAURI_MANIFEST
}
$env:CARGO_NET_OFFLINE = "true"
Write-Host "Tauri Rust dependencies fetched; Cargo offline mode enabled" -ForegroundColor Green
Write-Host ""

# Step 3: Build Tauri app
Write-Host "== Step 3: Building Tauri App ==" -ForegroundColor Yellow
$BUNDLE_DIR = Join-Path $REPO_ROOT "console\src-tauri\target\release\bundle"
$NSIS_DIR = Join-Path $BUNDLE_DIR "nsis"
if (Test-Path $NSIS_DIR) {
    Remove-Item -Recurse -Force $NSIS_DIR
}

Set-Location console

Write-Host "Building for Windows..."
npm exec -- tauri build --config src-tauri/tauri.version.conf.json
$tauriExit = $LASTEXITCODE

if ($tauriExit -ne 0) {
    throw "Tauri build failed"
}

Set-Location $REPO_ROOT
Write-Host "Tauri app built" -ForegroundColor Green

Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "Build Complete!" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "Output:"
Write-Host "  NSIS bundle directory: ${NSIS_DIR}\"
Write-Host ""
