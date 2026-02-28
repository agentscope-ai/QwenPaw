# CoPaw Installer for Windows
# Usage: irm <url>/install.ps1 | iex
#    or: .\install.ps1 [-Version X.Y.Z] [-FromSource [DIR]] [-Extras "llamacpp,mlx"]
#
# Installs CoPaw into ~/.copaw with a uv-managed Python environment.
# Users do NOT need Python pre-installed — uv handles everything.
#
# The entire script is wrapped in & { ... } @args so that `irm | iex` works
# correctly (param() is only valid inside a scriptblock/function/file scope).

& {
param(
    [string]$Version = "",
    [switch]$FromSource,
    [string]$SourceDir = "",
    [string]$Extras = "",
    [switch]$Help
)

$ErrorActionPreference = "Stop"

# ── Defaults ──────────────────────────────────────────────────────────────────
$CopawHome = if ($env:COPAW_HOME) { $env:COPAW_HOME } else { Join-Path $HOME ".copaw" }
$CopawVenv = Join-Path $CopawHome "venv"
$CopawBin = Join-Path $CopawHome "bin"
$PythonVersion = "3.12"
$CopawRepo = "https://github.com/agentscope-ai/CoPaw.git"

# ── Colors ────────────────────────────────────────────────────────────────────
function Write-Info { param([string]$Message) Write-Host "[copaw] " -ForegroundColor Green -NoNewline; Write-Host $Message }
function Write-Warn { param([string]$Message) Write-Host "[copaw] " -ForegroundColor Yellow -NoNewline; Write-Host $Message }
function Write-Err  { param([string]$Message) Write-Host "[copaw] " -ForegroundColor Red -NoNewline; Write-Host $Message }
function Stop-WithError { param([string]$Message) Write-Err $Message; exit 1 }

# ── Help ──────────────────────────────────────────────────────────────────────
if ($Help) {
    @"
CoPaw Installer for Windows

Usage: .\install.ps1 [OPTIONS]

Options:
  -Version <VER>        Install a specific version (e.g. 0.0.2)
  -FromSource [DIR]     Install from source. If DIR is given, use that local
                        directory; otherwise clone from GitHub.
  -Extras <EXTRAS>      Comma-separated optional extras to install
                        (e.g. llamacpp, mlx, llamacpp,mlx)
  -Help                 Show this help

Environment:
  COPAW_HOME            Installation directory (default: ~/.copaw)
"@
    exit 0
}

Write-Host "[copaw] " -ForegroundColor Green -NoNewline
Write-Host "Installing CoPaw into " -NoNewline
Write-Host "$CopawHome" -ForegroundColor White

# ── Execution Policy Check ────────────────────────────────────────────────────
$policy = Get-ExecutionPolicy
if ($policy -eq "Restricted") {
    Write-Info "Execution policy is 'Restricted', setting to RemoteSigned for current user..."
    try {
        Set-ExecutionPolicy RemoteSigned -Scope CurrentUser -Force
        Write-Info "Execution policy updated to RemoteSigned"
    } catch {
        Write-Err "PowerShell execution policy is set to 'Restricted' which prevents script execution."
        Write-Err "Please run the following command and retry:"
        Write-Err ""
        Write-Err "  Set-ExecutionPolicy RemoteSigned -Scope CurrentUser"
        Write-Err ""
        exit 1
    }
}

# ── Step 1: Ensure uv is available ───────────────────────────────────────────
function Ensure-Uv {
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        Write-Info "uv found: $((Get-Command uv).Source)"
        return
    }

    # Check common install locations not yet on PATH
    $candidates = @(
        (Join-Path $HOME ".local\bin\uv.exe"),
        (Join-Path $HOME ".cargo\bin\uv.exe"),
        (Join-Path $env:LOCALAPPDATA "uv\uv.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            $dir = Split-Path $candidate -Parent
            $env:PATH = "$dir;$env:PATH"
            Write-Info "uv found: $candidate"
            return
        }
    }

    Write-Info "Installing uv..."
    try {
        irm https://astral.sh/uv/install.ps1 | iex
    } catch {
        Stop-WithError "Failed to install uv. Please install it manually: https://docs.astral.sh/uv/"
    }

    # Refresh PATH after uv install
    $uvPaths = @(
        (Join-Path $HOME ".local\bin"),
        (Join-Path $HOME ".cargo\bin"),
        (Join-Path $env:LOCALAPPDATA "uv")
    )
    foreach ($p in $uvPaths) {
        if ((Test-Path $p) -and ($env:PATH -notlike "*$p*")) {
            $env:PATH = "$p;$env:PATH"
        }
    }

    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Stop-WithError "Failed to install uv. Please install it manually: https://docs.astral.sh/uv/"
    }
    Write-Info "uv installed successfully"
}

Ensure-Uv

# ── Step 2: Create / update virtual environment ──────────────────────────────
if (Test-Path $CopawVenv) {
    Write-Info "Existing environment found, upgrading..."
} else {
    Write-Info "Creating Python $PythonVersion environment..."
}

uv venv $CopawVenv --python $PythonVersion --quiet
if ($LASTEXITCODE -ne 0) { Stop-WithError "Failed to create virtual environment" }

$VenvPython = Join-Path $CopawVenv "Scripts\python.exe"
if (-not (Test-Path $VenvPython)) { Stop-WithError "Failed to create virtual environment" }

$pyVersion = & $VenvPython --version 2>&1
Write-Info "Python environment ready ($pyVersion)"

# ── Step 3: Install CoPaw ────────────────────────────────────────────────────
# Build extras suffix: "" or "[llamacpp,mlx]"
$ExtrasSuffix = ""
if ($Extras) {
    $ExtrasSuffix = "[$Extras]"
}

$script:ConsoleCopied = $false
$script:ConsoleAvailable = $false

function Prepare-Console {
    param([string]$RepoDir)

    $consoleSrc = Join-Path $RepoDir "console\dist"
    $consoleDest = Join-Path $RepoDir "src\copaw\console"

    # Already populated
    if (Test-Path (Join-Path $consoleDest "index.html")) { $script:ConsoleAvailable = $true; return }

    # Copy pre-built assets if available
    if ((Test-Path $consoleSrc) -and (Test-Path (Join-Path $consoleSrc "index.html"))) {
        Write-Info "Copying console frontend assets..."
        New-Item -ItemType Directory -Path $consoleDest -Force | Out-Null
        Copy-Item -Path "$consoleSrc\*" -Destination $consoleDest -Recurse -Force
        $script:ConsoleCopied = $true
        $script:ConsoleAvailable = $true
        return
    }

    # Try to build if npm is available
    $packageJson = Join-Path $RepoDir "console\package.json"
    if (-not (Test-Path $packageJson)) {
        Write-Warn "Console source not found - the web UI won't be available."
        return
    }

    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        Write-Warn "npm not found - skipping console frontend build."
        Write-Warn "Install Node.js from https://nodejs.org/ then re-run this installer,"
        Write-Warn "or run 'cd console && npm ci && npm run build' manually."
        return
    }

    Write-Info "Building console frontend (npm ci && npm run build)..."
    Push-Location (Join-Path $RepoDir "console")
    try {
        npm ci
        if ($LASTEXITCODE -ne 0) { Write-Warn "npm ci failed - the web UI won't be available."; return }
        npm run build
        if ($LASTEXITCODE -ne 0) { Write-Warn "npm run build failed - the web UI won't be available."; return }
    } finally {
        Pop-Location
    }
    if (Test-Path (Join-Path $consoleSrc "index.html")) {
        New-Item -ItemType Directory -Path $consoleDest -Force | Out-Null
        Copy-Item -Path "$consoleSrc\*" -Destination $consoleDest -Recurse -Force
        $script:ConsoleCopied = $true
        $script:ConsoleAvailable = $true
        Write-Info "Console frontend built successfully"
        return
    }

    Write-Warn "Console build completed but index.html not found - the web UI won't be available."
}

function Cleanup-Console {
    param([string]$RepoDir)
    if ($script:ConsoleCopied) {
        $consoleDest = Join-Path $RepoDir "src\copaw\console"
        if (Test-Path $consoleDest) {
            Remove-Item -Path "$consoleDest\*" -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

$VenvCopaw = Join-Path $CopawVenv "Scripts\copaw.exe"

if ($FromSource) {
    if ($SourceDir) {
        $SourceDir = (Resolve-Path $SourceDir).Path
        Write-Info "Installing CoPaw from local source: $SourceDir"
        Prepare-Console $SourceDir
        Write-Info "Installing package from source..."
        uv pip install "${SourceDir}${ExtrasSuffix}" --python $VenvPython --prerelease=allow
        if ($LASTEXITCODE -ne 0) { Stop-WithError "Installation from source failed" }
        Cleanup-Console $SourceDir
    } else {
        if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
            Stop-WithError "git is required for -FromSource without a local directory. Please install Git from https://git-scm.com/ or pass a local path: .\install.ps1 -FromSource -SourceDir C:\path\to\CoPaw"
        }
        Write-Info "Installing CoPaw from source (GitHub)..."
        $cloneDir = Join-Path $env:TEMP "copaw-install-$(Get-Random)"
        try {
            git clone --depth 1 $CopawRepo $cloneDir
            if ($LASTEXITCODE -ne 0) { Stop-WithError "Failed to clone repository" }
            Prepare-Console $cloneDir
            Write-Info "Installing package from source..."
            uv pip install "${cloneDir}${ExtrasSuffix}" --python $VenvPython --prerelease=allow
            if ($LASTEXITCODE -ne 0) { Stop-WithError "Installation from source failed" }
        } finally {
            if (Test-Path $cloneDir) {
                Remove-Item -Path $cloneDir -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
    }
} else {
    $package = "copaw"
    if ($Version) {
        $package = "copaw==$Version"
    }

    Write-Info "Installing ${package}${ExtrasSuffix} from PyPI..."
    uv pip install "${package}${ExtrasSuffix}" --python $VenvPython --prerelease=allow --quiet
    if ($LASTEXITCODE -ne 0) { Stop-WithError "Installation failed" }
}

# Verify the CLI entry point exists
if (-not (Test-Path $VenvCopaw)) { Stop-WithError "Installation failed: copaw CLI not found in venv" }

Write-Info "CoPaw installed successfully"

# Check console availability (for PyPI installs, check the installed package)
if (-not $script:ConsoleAvailable) {
    $consoleCheck = & $VenvPython -c "import importlib.resources, copaw; p=importlib.resources.files('copaw')/'console'/'index.html'; print('yes' if p.is_file() else 'no')" 2>&1
    if ($consoleCheck -eq "yes") { $script:ConsoleAvailable = $true }
}

# ── Step 4: Create wrapper script ────────────────────────────────────────────
New-Item -ItemType Directory -Path $CopawBin -Force | Out-Null

$wrapperPath = Join-Path $CopawBin "copaw.ps1"
$wrapperContent = @'
# CoPaw CLI wrapper — delegates to the uv-managed environment.
$ErrorActionPreference = "Stop"

$CopawHome = if ($env:COPAW_HOME) { $env:COPAW_HOME } else { Join-Path $HOME ".copaw" }
$RealBin = Join-Path $CopawHome "venv\Scripts\copaw.exe"

if (-not (Test-Path $RealBin)) {
    Write-Error "CoPaw environment not found at $CopawHome\venv"
    Write-Error "Please reinstall: irm <install-url> | iex"
    exit 1
}

& $RealBin @args
'@

Set-Content -Path $wrapperPath -Value $wrapperContent -Encoding UTF8
Write-Info "Wrapper created at $wrapperPath"

# Also create a .cmd wrapper for use from cmd.exe
$cmdWrapperPath = Join-Path $CopawBin "copaw.cmd"
$cmdWrapperContent = @"
@echo off
REM CoPaw CLI wrapper — delegates to the uv-managed environment.
set "COPAW_HOME=%COPAW_HOME%"
if "%COPAW_HOME%"=="" set "COPAW_HOME=%USERPROFILE%\.copaw"
set "REAL_BIN=%COPAW_HOME%\venv\Scripts\copaw.exe"
if not exist "%REAL_BIN%" (
    echo Error: CoPaw environment not found at %COPAW_HOME%\venv >&2
    echo Please reinstall: irm ^<install-url^> ^| iex >&2
    exit /b 1
)
"%REAL_BIN%" %*
"@

Set-Content -Path $cmdWrapperPath -Value $cmdWrapperContent -Encoding UTF8
Write-Info "CMD wrapper created at $cmdWrapperPath"

# ── Step 5: Update PATH via User Environment Variable ────────────────────────
# Use registry cmdlets instead of [Environment]:: static methods for compatibility
# with PowerShell Constrained Language Mode (e.g. when run via irm | iex).
$currentUserPath = (Get-ItemProperty -Path 'HKCU:\Environment' -Name 'Path' -ErrorAction SilentlyContinue).Path
if (-not $currentUserPath -or $currentUserPath -notlike "*$CopawBin*") {
    $newPath = if ($currentUserPath) { "$CopawBin;$currentUserPath" } else { $CopawBin }
    Set-ItemProperty -Path 'HKCU:\Environment' -Name 'Path' -Value $newPath
    $env:PATH = "$CopawBin;$env:PATH"
    Write-Info "Added $CopawBin to user PATH"
} else {
    Write-Info "$CopawBin already in PATH"
}

# ── Done ──────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "CoPaw installed successfully!" -ForegroundColor Green
Write-Host ""

# Install summary
Write-Host "  Install location:  " -NoNewline; Write-Host "$CopawHome" -ForegroundColor White
Write-Host "  Python:            " -NoNewline; Write-Host "$pyVersion" -ForegroundColor White
if ($script:ConsoleAvailable) {
    Write-Host "  Console (web UI):  " -NoNewline; Write-Host "available" -ForegroundColor Green
} else {
    Write-Host "  Console (web UI):  " -NoNewline; Write-Host "not available" -ForegroundColor Yellow
    Write-Host "                     Install Node.js and re-run to enable the web UI."
}
Write-Host ""

Write-Host "To get started, open a new terminal and run:"
Write-Host ""
Write-Host "  copaw init" -ForegroundColor White -NoNewline; Write-Host "       # first-time setup"
Write-Host "  copaw app" -ForegroundColor White -NoNewline; Write-Host "        # start CoPaw"
Write-Host ""
Write-Host "To upgrade later, re-run this installer."
Write-Host "To uninstall, run: " -NoNewline
Write-Host "copaw uninstall" -ForegroundColor White

} @args
