# Build QwenPaw backend with PyInstaller for Tauri sidecar (Windows)
# Creates an onedir backend bundle with embedded Python runtime
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

function Resolve-PythonRuntimeRoot {
    param([string]$PythonPath)

    $resolvedPython = (Resolve-Path -LiteralPath $PythonPath).Path
    $parent = Split-Path -Parent $resolvedPython
    $parentName = (Split-Path -Leaf $parent).ToLowerInvariant()
    if ($parentName -eq "scripts" -or $parentName -eq "bin") {
        return (Split-Path -Parent $parent)
    }
    return $parent
}

function Resolve-BasePythonForRuntime {
    param([string]$PythonPath)

    $script = @'
import os
import sys

if sys.version_info[:2] != (3, 10):
    raise SystemExit(0)

repo_root = os.path.realpath(os.environ.get("QWENPAW_REPO_ROOT", ""))
venv_root = os.path.realpath(os.path.join(repo_root, ".venv")) if repo_root else ""
candidates = []


def add(path):
    if path and path not in candidates:
        candidates.append(path)


add(getattr(sys, "_base_executable", ""))
for prefix in (getattr(sys, "base_prefix", ""), getattr(sys, "base_exec_prefix", ""), getattr(sys, "exec_prefix", "")):
    for rel in ("python.exe", os.path.join("Scripts", "python.exe"), os.path.join("bin", "python"), os.path.join("bin", "python3"), os.path.join("bin", "python3.10")):
        add(os.path.join(prefix, rel))

for candidate in candidates:
    raw = os.path.abspath(candidate)
    real = os.path.realpath(candidate)
    if not os.path.exists(candidate):
        continue
    if venv_root and (
        raw == venv_root
        or raw.startswith(venv_root + os.sep)
        or real == venv_root
        or real.startswith(venv_root + os.sep)
    ):
        continue
    print(candidate)
    break
'@

    $previousRepoRoot = $env:QWENPAW_REPO_ROOT
    try {
        $env:QWENPAW_REPO_ROOT = $REPO_ROOT
        $output = & $PythonPath -c $script
        if ($LASTEXITCODE -eq 0 -and $output) {
            $candidate = (($output | Select-Object -First 1) -as [string]).Trim()
            if ($candidate -and (Test-Path $candidate)) {
                return $candidate
            }
        }
    } finally {
        if ($null -eq $previousRepoRoot) {
            Remove-Item Env:\QWENPAW_REPO_ROOT -ErrorAction SilentlyContinue
        } else {
            $env:QWENPAW_REPO_ROOT = $previousRepoRoot
        }
    }

    return $null
}

function Stage-PythonRuntime {
    param([string]$Destination)

    if (-not $UV_BIN) {
        throw "uv is required to stage the Tauri Python runtime"
    }

    Write-Host "== Staging Python runtime ==" -ForegroundColor Yellow
    $runtimePython = Resolve-BasePythonForRuntime $PYTHON_BIN
    if ($runtimePython) {
        Write-Host "Using existing base Python runtime: $runtimePython" -ForegroundColor Green
    } else {
        Write-Host "No existing base Python runtime found; installing managed Python runtime with uv..." -ForegroundColor Yellow
        & $UV_BIN python install 3.10
        Assert-LastExit "Failed to install managed Python runtime with uv"

        $runtimePython = ((& $UV_BIN python find --managed-python 3.10) | Select-Object -First 1).Trim()
        Assert-LastExit "Failed to locate managed Python runtime with uv"
    }
    if (-not $runtimePython -or -not (Test-Path $runtimePython)) {
        throw "Python runtime executable not found: $runtimePython"
    }

    $runtimeRoot = Resolve-PythonRuntimeRoot $runtimePython
    if (-not (Test-Path $runtimeRoot)) {
        throw "Python runtime root not found: $runtimeRoot"
    }

    $runtimeDest = Join-Path $Destination "python-runtime"
    if (Test-Path $runtimeDest) {
        Remove-Item -LiteralPath $runtimeDest -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $runtimeDest | Out-Null
    Copy-Item -Recurse -Force (Join-Path $runtimeRoot "*") $runtimeDest

    $runtimeUv = Join-Path $runtimeDest "uv.exe"
    Copy-Item -Force $UV_BIN $runtimeUv
    Prune-PythonRuntime -RuntimeDir $runtimeDest
    Assert-PythonRuntimeExecutables -RuntimeDir $runtimeDest

    $packagedPython = Join-Path $runtimeDest "python.exe"
    if (-not (Test-Path $packagedPython)) {
        throw "Packaged runtime python.exe not found at $packagedPython"
    }
    if (-not (Test-Path $runtimeUv)) {
        throw "Packaged runtime uv.exe not found at $runtimeUv"
    }

    & $packagedPython -c "import sys; print('runtime python:', sys.executable); print(sys.version)"
    Assert-LastExit "Packaged runtime Python failed to start"
    & $runtimeUv --version
    Assert-LastExit "Packaged runtime uv failed to start"
    & $runtimeUv pip list --python $packagedPython *> $null
    Assert-LastExit "Packaged runtime uv cannot inspect the runtime Python"

    $runtimeSize = (Get-ChildItem $runtimeDest -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1MB
    Write-Host "Python runtime staged: $runtimeDest" -ForegroundColor Green
    Write-Host "Runtime size: $([math]::Round($runtimeSize, 2)) MB"
    Write-Host ""
}

function Prune-PythonRuntime {
    param([string]$RuntimeDir)

    $paths = @(
        (Join-Path $RuntimeDir "Scripts"),
        (Join-Path $RuntimeDir "Lib\venv"),
        (Join-Path $RuntimeDir "Lib\ensurepip"),
        (Join-Path $RuntimeDir "python3.exe"),
        (Join-Path $RuntimeDir "pythonw.exe"),
        (Join-Path $RuntimeDir "pythonw.pdb")
    )
    foreach ($path in $paths) {
        if (Test-Path $path) {
            Remove-Item -LiteralPath $path -Recurse -Force
        }
    }

    $sitePackages = Join-Path $RuntimeDir "Lib\site-packages"
    if (Test-Path $sitePackages) {
        Get-ChildItem -LiteralPath $sitePackages -Force |
            Where-Object {
                $_.Name -eq "pip" -or
                $_.Name -like "pip-*.dist-info" -or
                $_.Name -eq "setuptools" -or
                $_.Name -like "setuptools-*.dist-info" -or
                $_.Name -eq "wheel" -or
                $_.Name -like "wheel-*.dist-info"
            } |
            Remove-Item -Recurse -Force
    }

    Get-ChildItem -LiteralPath $RuntimeDir -File -Force |
        Where-Object {
            $_.Name -like "python-*.exe" -or
            $_.Name -like "python3*.exe" -or
            $_.Name -eq "pythonw.exe"
        } |
        Remove-Item -Force
}

function Assert-PythonRuntimeExecutables {
    param([string]$RuntimeDir)

    $allowed = @(
        (Join-Path $RuntimeDir "python.exe"),
        (Join-Path $RuntimeDir "uv.exe")
    )
    $unexpected = Get-ChildItem -LiteralPath $RuntimeDir -Recurse -File -Filter "*.exe" |
        Where-Object { $allowed -notcontains $_.FullName }
    if ($unexpected) {
        $relative = $unexpected |
            ForEach-Object { [System.IO.Path]::GetRelativePath($RuntimeDir, $_.FullName) }
        throw "Unexpected Python runtime executables: $($relative -join ', ')"
    }
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
Write-Host "Building onedir backend bundle..."

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
$BACKEND_DIR = Join-Path $DIST "pyinstaller\qwenpaw-backend"
$BACKEND_EXE = Join-Path $BACKEND_DIR "qwenpaw-backend.exe"
$CLI_EXE = Join-Path $BACKEND_DIR "qwenpaw.exe"
if (-not (Test-Path $BACKEND_DIR)) {
    Write-Host "ERROR: Backend bundle directory not found at $BACKEND_DIR" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $BACKEND_EXE)) {
    Write-Host "ERROR: Backend executable not found at $BACKEND_EXE" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $CLI_EXE)) {
    Write-Host "ERROR: CLI executable not found at $CLI_EXE" -ForegroundColor Red
    exit 1
}

Write-Host "Backend bundle created: $BACKEND_DIR" -ForegroundColor Green

# Get size
$bundleSize = (Get-ChildItem $BACKEND_DIR -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1MB
Write-Host "Bundle size: $([math]::Round($bundleSize, 2)) MB"
Write-Host ""

# Copy to Tauri resources directory
Write-Host "== Copying to Tauri binaries directory ==" -ForegroundColor Yellow
$BINARIES_DIR = Join-Path $REPO_ROOT "console\src-tauri\binaries"
New-Item -ItemType Directory -Force -Path $BINARIES_DIR | Out-Null

$DEST = Join-Path $BINARIES_DIR "qwenpaw-backend"
New-Item -ItemType Directory -Force -Path $DEST | Out-Null
Get-ChildItem -LiteralPath $DEST -Force | Remove-Item -Recurse -Force
Copy-Item -Recurse -Force (Join-Path $BACKEND_DIR "*") $DEST
Stage-PythonRuntime -Destination $DEST
Write-Host "Copied to: $DEST" -ForegroundColor Green
Write-Host ""

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "PyInstaller Build Complete!" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "Output:"
Write-Host "  Bundle: $BACKEND_DIR"
Write-Host "  Tauri resource: $DEST"
Write-Host ""
