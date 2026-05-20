# Build QwenPaw with Tauri for Windows using a conda-packed Python backend env.
#
# Windows and macOS Tauri packages share the same backend resource layout:
# binaries/qwenpaw-backend/env. The Rust shell starts Python from that env.

param()

$ErrorActionPreference = "Stop"
$REPO_ROOT = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $REPO_ROOT

$DIST = if ($env:DIST) { $env:DIST } else { "dist" }
if (-not [System.IO.Path]::IsPathRooted($DIST)) {
    $DIST = Join-Path $REPO_ROOT $DIST
}
$VERSION_FILE = "src\qwenpaw\__version__.py"

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
Write-Host "QwenPaw Tauri Build - Windows (conda env backend)" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "Version: $VERSION"
Write-Host ""

Write-Host "== Step 0: Checking prerequisites ==" -ForegroundColor Yellow
$missing = @()
foreach ($tool in @("npm", "rustc", "conda", "makensis")) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        Write-Host "  [MISSING] $tool" -ForegroundColor Red
        $missing += $tool
    } else {
        Write-Host "  [OK] $tool" -ForegroundColor Green
    }
}

if ($missing.Count -gt 0) {
    throw "Missing prerequisites: $($missing -join ', ')"
}
Write-Host ""

Write-Host "== Step 1: Building backend Python env ==" -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path $DIST | Out-Null
& powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\wheel_build.ps1
if ($LASTEXITCODE -ne 0) {
    throw "wheel_build.ps1 failed"
}

$archive = Join-Path $DIST "qwenpaw-tauri-backend-env.zip"
& python .\scripts\pack\build_common.py --output $archive --format zip --cache-wheels
if ($LASTEXITCODE -ne 0) {
    throw "build_common.py failed"
}

$backendResource = Join-Path $REPO_ROOT "console\src-tauri\binaries\qwenpaw-backend"
& python .\scripts\pack-tauri\stage_backend_env.py `
    --archive $archive `
    --resource-dir $backendResource `
    --precompile
if ($LASTEXITCODE -ne 0) {
    throw "stage_backend_env.py failed"
}
Write-Host "Tauri backend resource ready: $backendResource" -ForegroundColor Green
Write-Host ""

Write-Host "== Step 2: Building Tauri app ==" -ForegroundColor Yellow
$BUNDLE_DIR = Join-Path $REPO_ROOT "console\src-tauri\target\release\bundle"
$NSIS_DIR = Join-Path $BUNDLE_DIR "nsis"
if (Test-Path $NSIS_DIR) {
    Remove-Item -Recurse -Force $NSIS_DIR
}

Set-Location console
try {
    npm ci
    if ($LASTEXITCODE -ne 0) {
        throw "npm ci failed"
    }

    npm run sync:tauri-version
    if ($LASTEXITCODE -ne 0) {
        throw "Tauri version sync failed"
    }

    npm exec -- tauri build --config src-tauri/tauri.version.conf.json
    if ($LASTEXITCODE -ne 0) {
        throw "Tauri build failed"
    }
} finally {
    Set-Location $REPO_ROOT
}

Write-Host "Tauri app built" -ForegroundColor Green
Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "Build Complete!" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "Output:"
Write-Host "  NSIS bundle directory: $NSIS_DIR"
Write-Host ""
