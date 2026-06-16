# Build a conda-packed QwenPaw backend environment for Tauri (Windows).
# Run from the repository root, or let the script resolve it from its path.

param(
  [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $RepoRoot

$Dist = if ($env:DIST) { $env:DIST } else { "dist" }
if (-not [System.IO.Path]::IsPathRooted($Dist)) {
  $Dist = Join-Path $RepoRoot $Dist
}
if (-not $OutputDir) {
  $OutputDir = Join-Path $RepoRoot "console\src-tauri\binaries\qwenpaw-backend"
} elseif (-not [System.IO.Path]::IsPathRooted($OutputDir)) {
  $OutputDir = Join-Path $RepoRoot $OutputDir
}

$Archive = Join-Path $Dist "qwenpaw-env.zip"
$PackDir = Join-Path $RepoRoot "scripts\pack"
$BuildCommon = Join-Path $PackDir "build_common.py"
$ReusePackedEnv = $env:QWENPAW_REUSE_PACKED_ENV -eq "1"
$CompileAllMode = if ($env:QWENPAW_TAURI_COMPILEALL) {
  $env:QWENPAW_TAURI_COMPILEALL.ToLowerInvariant()
} else {
  "0"
}

$CondaUnpackAffectedPackages = @(
  "huggingface_hub",
  "discord.py"
)

function Get-QwenPawVersion {
  $versionFile = Join-Path $RepoRoot "src\qwenpaw\__version__.py"
  if (-not (Test-Path $versionFile)) {
    throw "Version file not found: $versionFile"
  }
  $content = Get-Content $versionFile -Raw
  if ($content -match '__version__\s*=\s*"([^"]+)"') {
    return $Matches[1]
  }
  throw "Failed to extract version from $versionFile"
}

function Ensure-QwenPawWheel {
  param([string]$Version)

  New-Item -ItemType Directory -Force -Path $Dist | Out-Null
  $wheelGlob = Join-Path $Dist "qwenpaw-$Version-*.whl"
  $existingWheels = Get-ChildItem -Path $wheelGlob -ErrorAction SilentlyContinue
  if ($existingWheels.Count -gt 0) {
    Write-Host "dist/ already has wheel for version $Version, skipping wheel build."
    return
  }

  $oldWheels = Get-ChildItem -Path (Join-Path $Dist "qwenpaw-*.whl") -ErrorAction SilentlyContinue
  if ($oldWheels.Count -gt 0) {
    Write-Host "Removing old wheel files: $($oldWheels | ForEach-Object { $_.Name })"
    $oldWheels | Remove-Item -Force
  }

  $wheelBuildScript = Join-Path $RepoRoot "scripts\wheel_build.ps1"
  if (-not (Test-Path $wheelBuildScript)) {
    throw "wheel_build.ps1 not found: $wheelBuildScript"
  }
  & $wheelBuildScript
  if ($LASTEXITCODE -ne 0) {
    throw "wheel_build.ps1 failed with exit code $LASTEXITCODE"
  }
}

function Resolve-EnvRoot {
  param([string]$Root)

  $envRoot = $Root
  if (-not (Test-Path (Join-Path $envRoot "python.exe"))) {
    $found = Get-ChildItem -Path $Root -Directory -ErrorAction SilentlyContinue |
      Where-Object { Test-Path (Join-Path $_.FullName "python.exe") } |
      Select-Object -First 1
    if ($found) {
      $envRoot = $found.FullName
    }
  }
  if (-not (Test-Path (Join-Path $envRoot "python.exe"))) {
    throw "python.exe not found in unpacked env (checked $Root and one level down)."
  }
  return ([System.IO.Path]::GetFullPath($envRoot))
}

function Invoke-CondaUnpackRepair {
  param([string]$EnvRoot)

  $condaUnpack = Join-Path $EnvRoot "Scripts\conda-unpack.exe"
  if (-not (Test-Path $condaUnpack)) {
    Write-Host "[tauri-conda] WARN: conda-unpack.exe not found at $condaUnpack, skipping."
    return
  }

  Write-Host "[tauri-conda] Running conda-unpack..."
  & $condaUnpack
  if ($LASTEXITCODE -ne 0) {
    throw "conda-unpack failed with exit code $LASTEXITCODE"
  }

  $wheelsCache = Join-Path $RepoRoot ".cache\conda_unpack_wheels"
  if (-not (Test-Path $wheelsCache)) {
    Write-Host "[tauri-conda] WARN: wheels cache not found at $wheelsCache" -ForegroundColor Yellow
    return
  }

  $pythonExe = Join-Path $EnvRoot "python.exe"
  foreach ($pkg in $CondaUnpackAffectedPackages) {
    Write-Host "[tauri-conda] Reinstalling $pkg after conda-unpack..."
    & $pythonExe -m pip install --force-reinstall --no-deps --find-links $wheelsCache --no-index $pkg
    if ($LASTEXITCODE -ne 0) {
      Write-Host "[tauri-conda] WARN: Failed to reinstall $pkg" -ForegroundColor Yellow
    }
  }

  & $pythonExe -c "from huggingface_hub import file_download; import discord; print('conda-unpack repair verified')"
  if ($LASTEXITCODE -ne 0) {
    throw "conda-unpack repair verification failed"
  }
}

function Write-QwenPawCliWrapper {
  param([string]$EnvRoot)

  $qwenpawCmd = Join-Path $EnvRoot "qwenpaw.cmd"
@"
@"%~dp0python.exe" -u -m qwenpaw %*
"@ | Set-Content -Path $qwenpawCmd -Encoding ASCII
}

function Clear-OutputDir {
  param([string]$Dest)

  $destFull = ([System.IO.Path]::GetFullPath($Dest)).TrimEnd([char[]]@("\", "/"))
  if (-not $destFull -or $destFull -eq [System.IO.Path]::GetPathRoot($destFull).TrimEnd([char[]]@("\", "/"))) {
    throw "Unsafe Tauri backend output directory: $Dest"
  }
  New-Item -ItemType Directory -Force -Path $Dest | Out-Null
  Get-ChildItem -LiteralPath $Dest -Force | Remove-Item -Recurse -Force
}

function Move-EnvRootToOutputDir {
  param(
    [string]$EnvRoot,
    [string]$Dest
  )

  $envRootFull = ([System.IO.Path]::GetFullPath($EnvRoot)).TrimEnd([char[]]@("\", "/"))
  $destFull = ([System.IO.Path]::GetFullPath($Dest)).TrimEnd([char[]]@("\", "/"))
  if ($envRootFull -ieq $destFull) {
    return $destFull
  }

  $flattenDir = Join-Path (Split-Path -Parent $destFull) ("qwenpaw-backend-flatten-" + [System.Guid]::NewGuid().ToString("N"))
  New-Item -ItemType Directory -Force -Path $flattenDir | Out-Null
  try {
    Get-ChildItem -LiteralPath $envRootFull -Force | Move-Item -Destination $flattenDir -Force
    Get-ChildItem -LiteralPath $destFull -Force | Remove-Item -Recurse -Force
    Get-ChildItem -LiteralPath $flattenDir -Force | Move-Item -Destination $destFull -Force
  } finally {
    if (Test-Path $flattenDir) {
      Remove-Item -LiteralPath $flattenDir -Recurse -Force
    }
  }
  return $destFull
}

function Invoke-OptionalCompileAll {
  param([string]$EnvRoot)

  $pythonExe = Join-Path $EnvRoot "python.exe"
  if (@("1", "true", "yes", "full") -contains $CompileAllMode) {
    Write-Host "== Pre-compiling Python bytecode =="
    & $pythonExe -m compileall -q -j 0 $EnvRoot
    if ($LASTEXITCODE -ne 0) {
      Write-Host "[tauri-conda] WARN: bytecode compilation had errors" -ForegroundColor Yellow
    }
    return
  }

  if ($CompileAllMode -eq "qwenpaw") {
    $packageDir = Join-Path $EnvRoot "Lib\site-packages\qwenpaw"
    if (Test-Path $packageDir) {
      Write-Host "== Pre-compiling QwenPaw Python bytecode =="
      & $pythonExe -m compileall -q $packageDir
      if ($LASTEXITCODE -ne 0) {
        Write-Host "[tauri-conda] WARN: QwenPaw bytecode compilation had errors" -ForegroundColor Yellow
      }
    } else {
      Write-Host "[tauri-conda] WARN: QwenPaw package not found for bytecode compilation: $packageDir" -ForegroundColor Yellow
    }
    return
  }

  Write-Host "== Skipping Python bytecode pre-compilation =="
  Write-Host "[tauri-conda] Set QWENPAW_TAURI_COMPILEALL=full to enable full compileall."
}

function Ensure-PackedArchive {
  param([string]$Version)

  if ($ReusePackedEnv) {
    Write-Host "== Using existing conda-packed env archive =="
    if (-not (Test-Path $Archive)) {
      throw "QWENPAW_REUSE_PACKED_ENV=1 but archive was not found: $Archive"
    }
    Write-Host "[tauri-conda] Reusing archive: $Archive"
    return
  }

  Ensure-QwenPawWheel -Version $Version

  Write-Host "== Building conda-packed env =="
  & python $BuildCommon --output $Archive --format zip --cache-wheels
  if ($LASTEXITCODE -ne 0) {
    throw "build_common.py failed with exit code $LASTEXITCODE"
  }
  if (-not (Test-Path $Archive)) {
    throw "Archive not created: $Archive"
  }
}

$version = Get-QwenPawVersion
Write-Host "========================================="
Write-Host "QwenPaw Tauri Backend - conda-pack (Windows)"
Write-Host "========================================="
Write-Host "Version: $version"
Write-Host "Output:  $OutputDir"
Write-Host ""

if (-not (Get-Command conda -ErrorAction SilentlyContinue) -and -not $env:CONDA_EXE) {
  throw "conda not found on PATH"
}
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  throw "python not found on PATH"
}
if (-not (Test-Path $BuildCommon)) {
  throw "build_common.py not found: $BuildCommon"
}

Ensure-PackedArchive -Version $version

Write-Host "== Unpacking env to Tauri resource directory =="
Clear-OutputDir -Dest $OutputDir
Expand-Archive -Path $Archive -DestinationPath $OutputDir -Force
$envRoot = Resolve-EnvRoot -Root $OutputDir
$envRoot = Move-EnvRootToOutputDir -EnvRoot $envRoot -Dest $OutputDir
Write-Host "[tauri-conda] Env root: $envRoot"

Invoke-CondaUnpackRepair -EnvRoot $envRoot
Invoke-OptionalCompileAll -EnvRoot $envRoot
Write-QwenPawCliWrapper -EnvRoot $envRoot

if (-not (Test-Path (Join-Path $OutputDir "python.exe"))) {
  throw "python.exe not found in Tauri backend resource: $OutputDir"
}
if (-not (Test-Path (Join-Path $OutputDir "qwenpaw.cmd"))) {
  throw "qwenpaw.cmd not found in Tauri backend resource: $OutputDir"
}

$bundleSize = (Get-ChildItem $OutputDir -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1MB
Write-Host "Backend resource ready: $OutputDir"
Write-Host "Resource size: $([math]::Round($bundleSize, 2)) MB"
$global:LASTEXITCODE = 0
