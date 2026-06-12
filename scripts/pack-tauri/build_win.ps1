# Build QwenPaw with Tauri for Windows (conda-pack backend).
#
# Usage:
#   powershell ./scripts/pack-tauri/build_win.ps1

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
Write-Host "QwenPaw Tauri Build - Windows (conda-pack)" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "Version: $VERSION"
Write-Host ""

Write-Host "== Step 0: Checking Prerequisites ==" -ForegroundColor Yellow
$missing = @()

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
  Write-Host "  [MISSING] npm" -ForegroundColor Red
  $missing += "npm"
} else {
  Write-Host "  [OK] npm ($(npm --version))" -ForegroundColor Green
}

if (-not (Get-Command conda -ErrorAction SilentlyContinue) -and -not $env:CONDA_EXE) {
  Write-Host "  [MISSING] conda" -ForegroundColor Red
  $missing += "conda"
} else {
  Write-Host "  [OK] conda" -ForegroundColor Green
}

if (-not (Get-Command rustc -ErrorAction SilentlyContinue)) {
  Write-Host "  [MISSING] rustc (Rust)" -ForegroundColor Red
  $missing += "rustc"
} else {
  Write-Host "  [OK] rustc ($(rustc --version))" -ForegroundColor Green
}

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
  $missing += "MSVC"
} else {
  Write-Host "  [OK] Visual Studio Build Tools (MSVC)" -ForegroundColor Green
}

if (-not (Get-Command makensis -ErrorAction SilentlyContinue)) {
  Write-Host "  [MISSING] makensis (NSIS)" -ForegroundColor Red
  $missing += "makensis"
} else {
  $nsisInfo = makensis /version 2>$null
  Write-Host "  [OK] makensis (NSIS $nsisInfo)" -ForegroundColor Green
}

if ($missing.Count -gt 0) {
  Write-Host ""
  Write-Host "Missing prerequisites: $($missing -join ', ')" -ForegroundColor Red
  exit 1
}
Write-Host ""

Write-Host "== Step 1: Building Console Static Assets ==" -ForegroundColor Yellow
Set-Location console
npm ci
if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }

Write-Host "Generating Tauri icons..."
npm exec -- tauri icon ../scripts/pack/assets/icon.svg
if ($LASTEXITCODE -ne 0) { throw "Tauri icon generation failed" }

Write-Host "Syncing Tauri version..."
node ../scripts/pack-tauri/sync_tauri_version.mjs
if ($LASTEXITCODE -ne 0) { throw "Tauri version sync failed" }

Write-Host "Building console frontend..."
npm run build:prod
if ($LASTEXITCODE -ne 0) { throw "console frontend build failed" }

Set-Location $REPO_ROOT
Write-Host "Console static assets built" -ForegroundColor Green
Write-Host ""

Write-Host "== Step 2: Building conda-packed backend ==" -ForegroundColor Yellow
$BACKEND_SCRIPT = Join-Path $REPO_ROOT "scripts\pack-tauri\build_conda_env.ps1"
& $BACKEND_SCRIPT
Write-Host "conda-packed backend ready" -ForegroundColor Green
Write-Host ""

Write-Host "== Step 3: Building Tauri App ==" -ForegroundColor Yellow
$BUNDLE_DIR = Join-Path $REPO_ROOT "console\src-tauri\target\release\bundle"
$NSIS_DIR = Join-Path $BUNDLE_DIR "nsis"
if (Test-Path $NSIS_DIR) {
  Remove-Item -Recurse -Force $NSIS_DIR
}

Set-Location console
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
