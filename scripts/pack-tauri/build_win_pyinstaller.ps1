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

# Step 1: Build PyInstaller backend
Write-Host "== Step 1: Building PyInstaller Backend ==" -ForegroundColor Yellow
$PYINSTALLER_SCRIPT = Join-Path $REPO_ROOT "scripts\pack-tauri\build_pyinstaller.ps1"
& powershell -ExecutionPolicy Bypass -File $PYINSTALLER_SCRIPT

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed"
}
Write-Host "PyInstaller backend ready" -ForegroundColor Green
Write-Host ""

# Step 2: Build console frontend and copy to Python package
Write-Host "== Step 2: Building Console Frontend ==" -ForegroundColor Yellow
Set-Location console

#if (-not (Test-Path "node_modules")) {
#    Write-Host "Installing frontend dependencies..."
#    bun install
#    if ($LASTEXITCODE -ne 0) {
#        throw "bun install failed"
#    }
#}

Write-Host "Installing frontend dependencies..."
bun install
if ($LASTEXITCODE -ne 0) {
    throw "bun install failed"
}

Write-Host "Building frontend..."
bun run build:prod
if ($LASTEXITCODE -ne 0) {
    throw "Frontend build failed"
}

Write-Host "Frontend built" -ForegroundColor Green
Set-Location $REPO_ROOT
Write-Host ""

# Step 3: Rebuild PyInstaller with embedded frontend
Write-Host "== Step 3: Rebuilding PyInstaller with embedded frontend ==" -ForegroundColor Yellow
& powershell -ExecutionPolicy Bypass -File $PYINSTALLER_SCRIPT

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller rebuild failed"
}
Write-Host "PyInstaller backend rebuilt with frontend" -ForegroundColor Green
Write-Host ""

# Step 3.5: Ensure NSIS is available for Tauri bundling
# Workaround for https://github.com/tauri-apps/tauri/issues/9895
# Jenkins service users have AppData in a restricted system profile,
# so Tauri's default NSIS download location is blocked by Windows security.
# We download NSIS to the workspace instead and set NSIS_PATH.
Write-Host "== Step 3.5: Ensuring NSIS is available ==" -ForegroundColor Yellow
$NSIS_DIR = Join-Path $DIST "tools\nsis"
$MAKENSIS = Join-Path $NSIS_DIR "makensis.exe"
if (-not (Test-Path $MAKENSIS)) {
    Write-Host "Downloading NSIS..."
    $NSIS_ZIP = Join-Path $DIST "tools\nsis-3.11.zip"
    New-Item -ItemType Directory -Force -Path (Split-Path $NSIS_ZIP) | Out-Null
    Invoke-WebRequest -Uri "https://github.com/tauri-apps/binary-releases/releases/download/nsis-3.11/nsis-3.11.zip" -OutFile $NSIS_ZIP
    Expand-Archive -Path $NSIS_ZIP -DestinationPath $NSIS_DIR -Force
    Remove-Item $NSIS_ZIP
}
$env:NSIS_PATH = $NSIS_DIR
Write-Host "NSIS path: $NSIS_DIR" -ForegroundColor Green
Write-Host ""

# Step 4: Build Tauri app
Write-Host "== Step 4: Building Tauri App ==" -ForegroundColor Yellow
Set-Location console

Write-Host "Building for Windows..."
bun tauri build
if ($LASTEXITCODE -ne 0) {
    throw "Tauri build failed"
}

Set-Location $REPO_ROOT
Write-Host "Tauri app built" -ForegroundColor Green
Write-Host ""

# Step 5: Create distribution
Write-Host "== Step 5: Creating Distribution ==" -ForegroundColor Yellow

$BUNDLE_DIR = "console\src-tauri\target\release\bundle"
$MSI_PATH = $null

if (Test-Path "$BUNDLE_DIR\msi") {
    $MSI_PATH = Get-ChildItem "$BUNDLE_DIR\msi\*.msi" | Select-Object -First 1
}

New-Item -ItemType Directory -Force -Path "${DIST}\tauri-windows" | Out-Null

if ($MSI_PATH) {
    Copy-Item -Force $MSI_PATH.FullName "${DIST}\tauri-windows\"
    Write-Host "MSI copied to ${DIST}\tauri-windows\" -ForegroundColor Green
}

# Also copy NSIS installer if present
if (Test-Path "$BUNDLE_DIR\nsis") {
    $NSIS_EXE = Get-ChildItem "$BUNDLE_DIR\nsis\*.exe" | Select-Object -First 1
    if ($NSIS_EXE) {
        Copy-Item -Force $NSIS_EXE.FullName "${DIST}\tauri-windows\"
        Write-Host "NSIS installer copied to ${DIST}\tauri-windows\" -ForegroundColor Green
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
    "${DIST}\tauri-windows",
    $ZIP_NAME,
    [System.IO.Compression.CompressionLevel]::Optimal,
    $true
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
Write-Host "  Directory: ${DIST}\tauri-windows\"
Write-Host "  Distribution: $ZIP_NAME"
Write-Host ""
