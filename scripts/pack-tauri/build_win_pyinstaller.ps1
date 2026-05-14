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

# Step 1: Build PyInstaller backend
Write-Host "== Step 1: Building PyInstaller Backend ==" -ForegroundColor Yellow
$PYINSTALLER_SCRIPT = Join-Path $REPO_ROOT "scripts\pack-tauri\build_pyinstaller.ps1"
& $PYINSTALLER_SCRIPT

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed"
}
Write-Host "PyInstaller backend ready" -ForegroundColor Green
Write-Host ""

# Step 2: Build Tauri app
# Note: Tauri caches NSIS/Wix tools in target/.tauri/ via useLocalToolsDir
# in tauri.conf.json — no LOCALAPPDATA redirect needed.
Write-Host "== Step 2: Building Tauri App ==" -ForegroundColor Yellow
$BUNDLE_DIR = Join-Path $REPO_ROOT "console\src-tauri\target\release\bundle"
$NSIS_DIR = Join-Path $BUNDLE_DIR "nsis"
if (Test-Path $NSIS_DIR) {
    Remove-Item -Recurse -Force $NSIS_DIR
}

Set-Location console

Write-Host "Installing frontend dependencies..."
npm ci
if ($LASTEXITCODE -ne 0) {
    throw "npm ci failed"
}

Write-Host "Syncing Tauri version..."
npm run sync:tauri-version
if ($LASTEXITCODE -ne 0) {
    throw "Tauri version sync failed"
}

Write-Host "Building for Windows..."
npm exec -- tauri build --config src-tauri/tauri.version.conf.json
$tauriExit = $LASTEXITCODE

if ($tauriExit -ne 0) {
    throw "Tauri build failed"
}

Set-Location $REPO_ROOT
Write-Host "Tauri app built" -ForegroundColor Green
Write-Host ""

# Step 3: Create distribution
Write-Host "== Step 3: Creating Distribution ==" -ForegroundColor Yellow

$DIST_TAURI_DIR = Join-Path $DIST "tauri-windows"
if (Test-Path $DIST_TAURI_DIR) {
    Remove-Item -Recurse -Force $DIST_TAURI_DIR
}
New-Item -ItemType Directory -Force -Path $DIST_TAURI_DIR | Out-Null

# Copy NSIS installer if present
if (Test-Path $NSIS_DIR) {
    $NSIS_EXE = Get-ChildItem -Path $NSIS_DIR -Filter "*.exe" -File |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($NSIS_EXE) {
        Copy-Item -Force $NSIS_EXE.FullName $DIST_TAURI_DIR
        Write-Host "NSIS installer copied to ${DIST_TAURI_DIR}\" -ForegroundColor Green
    }
}

# Create ZIP archive
Write-Host ""
Write-Host "Creating distribution archive..."
$ZIP_NAME = "${DIST}\QwenPaw-Tauri-${VERSION}-Windows.zip"
if (Test-Path $ZIP_NAME) {
    Remove-Item -Force $ZIP_NAME
}

Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory(
    $DIST_TAURI_DIR,
    $ZIP_NAME,
    [System.IO.Compression.CompressionLevel]::Optimal,
    $false
)

if (Test-Path $ZIP_NAME) {
    $zipSize = (Get-Item $ZIP_NAME).Length / 1MB
    Write-Host "Created $ZIP_NAME ($([math]::Round($zipSize, 2)) MB)" -ForegroundColor Green
} else {
    Write-Host "ERROR: Failed to create ZIP archive" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "Build Complete!" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "Output:"
Write-Host "  Directory: ${DIST_TAURI_DIR}\"
Write-Host "  Distribution: $ZIP_NAME"
Write-Host ""
