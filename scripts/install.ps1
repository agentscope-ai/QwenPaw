# CoPaw Installer for Windows (self-contained: includes uv download via GitHub)
# Usage: irm <url>/install.ps1 | iex
#    or: .\install.ps1 [-Version X.Y.Z] [-FromSource] [-SourceDir DIR]
#                            [-Extras "llamacpp,mlx"] [-UvPath PATH]
#
# Installs CoPaw into ~/.copaw with a uv-managed Python environment.
# Users do NOT need Python pre-installed — uv handles everything.
#
# uv is obtained automatically (no action required from the user):
#   1. Already on PATH or in common locations
#   2. Downloaded via https://astral.sh/uv/install.ps1
#   3. Downloaded via GitHub Releases if astral.sh is unreachable (e.g. in China)
#
# The entire script is wrapped in & { ... } @args so that `irm | iex` works
# correctly (param() is only valid inside a scriptblock/function/file scope).

& {
param(
    [string]$Version   = "",
    [switch]$FromSource,
    [string]$SourceDir = "",
    [string]$Extras    = "",
    [string]$UvPath    = "",
    [switch]$Help
)

$ErrorActionPreference = "Stop"

# ── Defaults ──────────────────────────────────────────────────────────────────
$CopawHome     = if ($env:COPAW_HOME) { $env:COPAW_HOME } else { Join-Path $HOME ".copaw" }
$CopawVenv     = Join-Path $CopawHome "venv"
$CopawBin      = Join-Path $CopawHome "bin"
$PythonVersion = "3.12"
$CopawRepo     = "https://github.com/agentscope-ai/CoPaw.git"

# ── Colors ────────────────────────────────────────────────────────────────────
function Write-Info { param([string]$Message) Write-Host "[copaw] " -ForegroundColor Green  -NoNewline; Write-Host $Message }
function Write-Warn { param([string]$Message) Write-Host "[copaw] " -ForegroundColor Yellow -NoNewline; Write-Host $Message }
function Write-Err  { param([string]$Message) Write-Host "[copaw] " -ForegroundColor Red    -NoNewline; Write-Host $Message }
function Stop-WithError { param([string]$Message) Write-Err $Message; exit 1 }

# ── Help ──────────────────────────────────────────────────────────────────────
if ($Help) {
    @"
CoPaw Installer for Windows

Usage: .\install.ps1 [OPTIONS]

Options:
  -Version <VER>        Install a specific version (e.g. 0.0.2)
  -FromSource           Install from source (requires git, or use -SourceDir)
  -SourceDir <DIR>      Local source directory (used with -FromSource)
  -Extras <EXTRAS>      Comma-separated optional extras to install
                        (e.g. llamacpp, mlx, llamacpp,mlx)
  -UvPath <PATH>        Path to a pre-installed uv.exe (skips all auto-install)
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

function Invoke-UvFromGitHub {
    # Downloads uv from GitHub Releases and prepends its directory to PATH.
    # Used automatically when astral.sh is unreachable (e.g. in China).
    $arch = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "aarch64" } else { "x86_64" }
    $url  = "https://github.com/astral-sh/uv/releases/latest/download/uv-$arch-pc-windows-msvc.zip"
    $dest = Join-Path $env:LOCALAPPDATA "uv"
    $zip  = Join-Path $env:TEMP "uv-gh-$([System.IO.Path]::GetRandomFileName()).zip"

    Write-Info "Downloading uv ($arch) from GitHub Releases..."
    $ProgressPreference = 'SilentlyContinue'   # prevents 100x slowdown in PS 5.1
    try {
        Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    } catch {
        throw "GitHub download failed: $_"
    }

    if (-not (Test-Path $dest)) { New-Item -ItemType Directory -Path $dest -Force | Out-Null }

    Write-Info "Extracting uv..."
    try {
        Expand-Archive -Force -Path $zip -DestinationPath $dest
    } catch {
        Remove-Item $zip -ErrorAction SilentlyContinue
        throw "Extraction failed: $_"
    }
    Remove-Item $zip -ErrorAction SilentlyContinue

    $uvExe = Join-Path $dest "uv.exe"
    if (-not (Test-Path $uvExe)) { throw "uv.exe not found after extraction at $dest" }

    $env:PATH = "$dest;$env:PATH"
    Write-Info "uv installed from GitHub: $uvExe"
}

function Ensure-Uv {
    # 0. User-supplied path (-UvPath)
    if ($UvPath) {
        if (-not (Test-Path $UvPath)) { Stop-WithError "Specified uv not found: $UvPath" }
        $env:PATH = "$(Split-Path $UvPath -Parent);$env:PATH"
        Write-Info "uv found: $UvPath"
        return
    }

    # 1. Already on PATH
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        Write-Info "uv found: $((Get-Command uv).Source)"
        return
    }

    # 2. Common install locations not yet on PATH
    $candidates = @(
        (Join-Path $HOME ".local\bin\uv.exe"),
        (Join-Path $HOME ".cargo\bin\uv.exe"),
        (Join-Path $env:LOCALAPPDATA "uv\uv.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            $env:PATH = "$(Split-Path $candidate -Parent);$env:PATH"
            Write-Info "uv found: $candidate"
            return
        }
    }

    # 3. Try astral.sh (standard installer, fast outside China)
    Write-Warn "If automatic uv installation fails, please manually install uv first by following https://github.com/astral-sh/uv/releases, then re-run this installer."
    Write-Warn "Alternatively, if Python is already installed, run: python -m pip install -U uv"
    Write-Info "Installing uv via astral.sh..."
    $astralOk = $false
    try {
        $installScript = Invoke-RestMethod https://astral.sh/uv/install.ps1 -TimeoutSec 15
        Invoke-Expression $installScript
        $astralOk = $true
    } catch {
        Write-Warn "astral.sh unreachable, falling back to GitHub Releases..."
    }

    if ($astralOk) {
        # Refresh PATH after astral.sh install
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
        if (Get-Command uv -ErrorAction SilentlyContinue) {
            Write-Info "uv installed via astral.sh"
            return
        }
        Write-Warn "astral.sh install succeeded but uv not found on PATH, trying GitHub Releases..."
    }

    # 4. GitHub Releases fallback (works in China)
    try {
        Invoke-UvFromGitHub
    } catch {
        Stop-WithError "Failed to install uv automatically: $_`nPlease install uv manually: https://docs.astral.sh/uv/"
    }
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Stop-WithError "Failed to install uv. Please install it manually: https://docs.astral.sh/uv/"
    }
}

Ensure-Uv

# ── Step 2: Create / update virtual environment ──────────────────────────────
if (Test-Path $CopawVenv) {
    Write-Info "Existing environment found, upgrading..."
} else {
    Write-Info "Creating Python $PythonVersion environment..."
}

uv venv $CopawVenv --python $PythonVersion --quiet --clear
if ($LASTEXITCODE -ne 0) { Stop-WithError "Failed to create virtual environment" }

$VenvPython = Join-Path $CopawVenv "Scripts\python.exe"
if (-not (Test-Path $VenvPython)) { Stop-WithError "Failed to create virtual environment" }

$pyVersion = & $VenvPython --version 2>&1
Write-Info "Python environment ready ($pyVersion)"

# ── Step 3: Install CoPaw ────────────────────────────────────────────────────
$ExtrasSuffix = ""
if ($Extras) { $ExtrasSuffix = "[$Extras]" }

$script:ConsoleCopied   = $false
$script:ConsoleAvailable = $false

function Prepare-Console {
    param([string]$RepoDir)

    $consoleSrc  = Join-Path $RepoDir "console\dist"
    $consoleDest = Join-Path $RepoDir "src\copaw\console"

    # Already populated
    if (Test-Path (Join-Path $consoleDest "index.html")) { $script:ConsoleAvailable = $true; return }

    # Copy pre-built assets if available
    if ((Test-Path $consoleSrc) -and (Test-Path (Join-Path $consoleSrc "index.html"))) {
        Write-Info "Copying console frontend assets..."
        New-Item -ItemType Directory -Path $consoleDest -Force | Out-Null
        Copy-Item -Path "$consoleSrc\*" -Destination $consoleDest -Recurse -Force
        $script:ConsoleCopied   = $true
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
        $script:ConsoleCopied   = $true
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
    if ($Version) { $package = "copaw==$Version" }

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

# ── Step 4: Create wrapper scripts ───────────────────────────────────────────
New-Item -ItemType Directory -Path $CopawBin -Force | Out-Null

$wrapperPath = Join-Path $CopawBin "copaw.ps1"
$wrapperContent = @'
# CoPaw CLI wrapper — delegates to the uv-managed environment.
$ErrorActionPreference = "Stop"

$CopawHome = if ($env:COPAW_HOME) { $env:COPAW_HOME } else { Join-Path $HOME ".copaw" }
$RealBin   = Join-Path $CopawHome "venv\Scripts\copaw.exe"

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

# ──Step 5: Update PATH via User Environment Variable ────────────────────────
$targetPath = $CopawBin
$registryPath = "HKCU:\Environment"
$registryName = "Path"

# 1. 安全获取当前的 User PATH (直接从注册表读取，避免污染 Machine PATH)
try {
    $currentUserPath = (Get-ItemProperty -Path $registryPath -Name $registryName -ErrorAction SilentlyContinue).Path
    if (-not $currentUserPath) { $currentUserPath = "" }
} catch {
    # 如果连读都失败（极罕见），则从头开始
    $currentUserPath = ""
    Write-Debug "Could not read User Path from registry, starting fresh."
}

# 2. 精确检查是否已存在 (解决前缀匹配误判)
# 分割路径并去除空格
$pathArray = $currentUserPath -split ';' | ForEach-Object { $_.Trim() }
$isAlreadyAdded = $pathArray -contains $targetPath

if (-not $isAlreadyAdded) {
    # 构建新的 User PATH 字符串
    if ($currentUserPath) {
        $newUserPath = "$targetPath;$currentUserPath"
    } else {
        $newUserPath = $targetPath
    }

    # 3. 核心修复：使用 SetItemProperty 代替 [Environment]::SetEnvironmentVariable
    #    这是原生 cmdlet，在 Constrained Language Mode 下通常可用
    try {
        # 确保注册表路径存在 (HKCU:\Environment 通常默认存在，但为了健壮性检查一下)
        if (-not (Test-Path $registryPath)) {
            # 这种情况极少见，但如果发生，尝试创建（通常需要权限，若失败则进入 catch）
            New-Item -Path $registryPath -Force | Out-Null
        }

        # 写入注册表
        SetItemProperty -Path $registryPath -Name $registryName -Value $newUserPath

        # 更新当前进程的环境变量，使当前终端立即生效
        $env:Path = "$targetPath;$env:Path"

        Write-Info "Successfully added $targetPath to User PATH (via Registry)"

    } catch {
        # 如果连 SetItemProperty 都失败（例如注册表被组策略完全锁定）
        $errorMsg = $_.Exception.Message

        Write-Host ""
        Write-Host "[CRITICAL WARNING] Automatic PATH update failed." -ForegroundColor Red
        Write-Host "   Reason: $errorMsg"
        Write-Host "   Context: Your system policy strictly blocks environment modifications."
        Write-Host ""
        Write-Host "ACTION REQUIRED: You must manually add the path to use CoPaw."
        Write-Host "   Target Path: $targetPath"
        Write-Host ""
        Write-Host "Manual Steps (User Variables):"
        Write-Host "   1. Press Win+R, type 'sysdm.cpl' and press Enter"
        Write-Host "   2. Go to [Advanced] > [Environment Variables...]"
        Write-Host "   3. In the TOP section ('User variables'), select 'Path' > [Edit]"
        Write-Host "      (If 'Path' doesn't exist in User variables, click [New] and name it 'Path')"
        Write-Host "   4. Click [New] and paste: $targetPath"
        Write-Host "   5. Click [OK] everywhere to save."
        Write-Host "   6. CLOSE and REOPEN your terminal."
        Write-Host ""

        # 即使注册表写入失败，也尝试更新当前会话以便用户测试（如果不报错的话）
        # 注意：如果策略极严，这行也可能无效，但尝试一下无害
        try {
            $env:Path = "$targetPath;$env:Path"
        } catch {}
    }
} else {
    Write-Info "$targetPath is already in your User PATH"
}

# ── Done ──────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "CoPaw installed successfully!" -ForegroundColor Green
Write-Host ""

Write-Host "  Install location:  " -NoNewline; Write-Host "$CopawHome" -ForegroundColor White
Write-Host "  Python:            " -NoNewline; Write-Host "$pyVersion"  -ForegroundColor White
if ($script:ConsoleAvailable) {
    Write-Host "  Console (web UI):  " -NoNewline; Write-Host "available"     -ForegroundColor Green
} else {
    Write-Host "  Console (web UI):  " -NoNewline; Write-Host "not available" -ForegroundColor Yellow
    Write-Host "                     Install Node.js and re-run to enable the web UI."
}
Write-Host ""

Write-Host "To get started, open a new terminal and run:"
Write-Host ""
Write-Host "  copaw init" -ForegroundColor White -NoNewline; Write-Host "       # first-time setup"
Write-Host "  copaw app"  -ForegroundColor White -NoNewline; Write-Host "        # start CoPaw"
Write-Host ""
Write-Host "To upgrade later, re-run this installer."
Write-Host "To uninstall, run: " -NoNewline
Write-Host "copaw uninstall" -ForegroundColor White

} @args
