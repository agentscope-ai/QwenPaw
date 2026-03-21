# Electron build script for RyPaw Desktop
# Replaces the old pywebview + NSIS approach

$ErrorActionPreference = "Stop"
$RepoRoot = (Get-Item $PSScriptRoot).Parent.Parent.FullName
Set-Location $RepoRoot
Write-Host "[build_electron] REPO_ROOT=$RepoRoot"

$Dist = Join-Path $RepoRoot "dist"
$ElectronDir = Join-Path $RepoRoot "electron"
$PythonRuntimeDir = Join-Path $Dist "python-runtime"

# Clean previous builds (use cmd /c rd to handle symlinks/.lnk files that PowerShell can't delete)
if (Test-Path $Dist) {
  cmd /c "rd /s /q `"$Dist`""
  if (Test-Path $Dist) {
    Remove-Item -Recurse -Force $Dist -ErrorAction SilentlyContinue
  }
}
New-Item -ItemType Directory -Force -Path $Dist | Out-Null

Write-Host "== Step 1: Building console frontend =="
Set-Location (Join-Path $RepoRoot "console")
npm run build
if ($LASTEXITCODE -ne 0) { throw "Console build failed" }
Set-Location $RepoRoot

Write-Host "== Step 2: Building Python wheel =="
$WheelBuildScript = Join-Path $RepoRoot "scripts\wheel_build.ps1"
if (Test-Path $WheelBuildScript) {
  & $WheelBuildScript
  if ($LASTEXITCODE -ne 0) { throw "Wheel build failed" }
} else {
  Write-Host "[build_electron] Wheel build script not found, skipping..."
}

Write-Host "== Step 3: Creating portable Python runtime =="
# Use conda-pack with exclusions to reduce warnings
Write-Host "[build_electron] Using conda-pack for Python runtime..."

$Archive = Join-Path $Dist "rypaw-env.zip"
& python (Join-Path $PSScriptRoot "build_common.py") --output $Archive --format zip --cache-wheels 2>&1 | Select-String -Pattern "^(Packed|Caching|Verifying|conda-pack)" | ForEach-Object { Write-Host $_.ToString() }
if ($LASTEXITCODE -ne 0) { throw "build_common.py failed" }

# Extract to python-runtime directory
Write-Host "[build_electron] Extracting Python runtime..."
try {
  Expand-Archive -Path $Archive -DestinationPath $PythonRuntimeDir -Force -ErrorAction Stop
} catch {
  Write-Host "[build_electron] WARN: Some files had extraction warnings (non-critical)"
}

# The extracted archive usually has one nested directory
$Extracted = Get-ChildItem -Path $PythonRuntimeDir -Directory -ErrorAction SilentlyContinue
if ($Extracted.Count -eq 1) {
  Write-Host "[build_electron] Flattening extracted directory..."
  Get-ChildItem -Path $Extracted[0].FullName | Move-Item -Destination $PythonRuntimeDir -Force
  Remove-Item $Extracted[0].FullName -Force
}

# Verify Python executable exists (may be at root or in Scripts/ subdirectory)
$PythonExe = $null
$PossiblePaths = @(
  (Join-Path $PythonRuntimeDir "python.exe"),
  (Join-Path $PythonRuntimeDir "Scripts\python.exe")
)

foreach ($Path in $PossiblePaths) {
  if (Test-Path $Path) {
    $PythonExe = $Path
    break
  }
}

if (-not $PythonExe) {
  Write-Host "[build_electron] ERROR: Python executable not found after extraction"
  Write-Host "[build_electron] Extracted contents:"
  Get-ChildItem -Path $PythonRuntimeDir | Select-Object -First 20
  throw "Python executable not found"
}
Write-Host "[build_electron] Found Python at: $PythonExe"

# Run conda-unpack to fix paths (suppress warnings)
$CondaUnpack = Join-Path $PythonRuntimeDir "Scripts\conda-unpack.exe"
if (-not (Test-Path $CondaUnpack)) {
  # Try alternative location
  $CondaUnpack = Join-Path $PythonRuntimeDir "conda-unpack.exe"
}

if (Test-Path $CondaUnpack) {
  Write-Host "[build_electron] Running conda-unpack to fix hardcoded paths..."
  & $CondaUnpack
  if ($LASTEXITCODE -ne 0) {
    throw "conda-unpack failed with exit code $LASTEXITCODE"
  }
  Write-Host "[build_electron] conda-unpack completed successfully"
} else {
  Write-Host "[build_electron] WARN: conda-unpack not found, skipping"
}

Write-Host "== Step 4: Copying console build =="
$ConsoleDist = Join-Path $RepoRoot "console\dist"
if (Test-Path $ConsoleDist) {
  Copy-Item -Path $ConsoleDist\* -Destination (Join-Path $Dist "console") -Recurse -Force
  Write-Host "[build_electron] Console build copied"
} else {
  Write-Host "[build_electron] WARN: Console dist not found at $ConsoleDist"
}

Write-Host "== Step 5: Installing Electron dependencies =="
Set-Location $ElectronDir
npm install
if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
Set-Location $RepoRoot

Write-Host "== Step 6: Building Electron application =="
Set-Location $ElectronDir

# Set version from __version__.py
$VersionFile = Join-Path $RepoRoot "src\rypaw\__version__.py"
if (Test-Path $VersionFile) {
  $Version = (Select-String -Path $VersionFile -Pattern '__version__\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
  Write-Host "[build_electron] Raw rypaw version: $Version"

  # Convert Python version (e.g., 0.0.7.post1) to semver (e.g., 0.0.7-post1)
  # electron-builder requires valid semver format
  if ($Version -match '\.post(\d+)') {
    $ElectronVersion = $Version -replace '\.post(\d+)', '-post$1'
  } else {
    $ElectronVersion = $Version
  }
  Write-Host "[build_electron] Electron version: $ElectronVersion"

  # Replace version while preserving the comma
  (Get-Content $ElectronDir\package.json) -replace '"version": ".*"', "`"version`": `"$ElectronVersion`"" | Set-Content $ElectronDir\package.json
}

# Build for Windows
npm run build:win
if ($LASTEXITCODE -ne 0) { throw "Electron build failed" }

Set-Location $RepoRoot

Write-Host "== Build complete! =="
Write-Host "[build_electron] Output: dist\RyPaw-Desktop-*.exe"
Write-Host "[build_electron] You can now install and run the application!"
