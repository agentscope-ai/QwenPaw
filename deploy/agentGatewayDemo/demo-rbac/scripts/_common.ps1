# demo-rbac shared paths (portable layout)
# DeployRoot/
#   agentgateway.exe
#   demo-rbac/

$Script:DemoRoot = Split-Path -Parent $PSScriptRoot
$Script:DeployRoot = Split-Path -Parent $Script:DemoRoot

function Join-DeployPath {
    param([string]$Relative)
    Join-Path $Script:DeployRoot ($Relative -replace '/', '\')
}

function Join-DemoPath {
    param([string]$Relative)
    Join-Path $Script:DemoRoot ($Relative -replace '/', '\')
}

function Install-DemoPythonDeps {
    Write-Host "Installing MCP dependencies (if needed)..." -ForegroundColor DarkGray
    $reqHr = Join-DemoPath "mcp-hr\requirements.txt"
    $reqForum = Join-DemoPath "mcp-forum\requirements.txt"
    $reqDemo = Join-DemoPath "requirements.txt"
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & python -m pip install -q -r $reqHr -r $reqForum -r $reqDemo 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "WARN: pip install exit code $LASTEXITCODE (skip if mcp already installed)" -ForegroundColor Yellow
        }
    } finally {
        $ErrorActionPreference = $prev
    }
}

function Assert-AgentGateway {
    $exe = Join-DeployPath "agentgateway.exe"
    if (-not (Test-Path $exe)) {
        Write-Host "ERROR: agentgateway.exe not found" -ForegroundColor Red
        Write-Host "  Expected: $exe" -ForegroundColor Red
        Write-Host "  Put agentgateway.exe and demo-rbac folder in the same directory." -ForegroundColor Yellow
        exit 1
    }
    return $exe
}

function Set-DeployLocation {
    Set-Location $Script:DeployRoot
}

function Test-NodeToolchain {
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
        Write-Host "ERROR: node not found. Install Node.js 18+ from https://nodejs.org/" -ForegroundColor Red
        return $false
    }
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        Write-Host "ERROR: npm not found. Install Node.js (includes npm)." -ForegroundColor Red
        return $false
    }
    return $true
}

function Ensure-McpInspector {
    if (-not (Test-NodeToolchain)) {
        exit 1
    }
    if (Get-Command mcp-inspector -ErrorAction SilentlyContinue) {
        return
    }
    Write-Host "Installing MCP Inspector globally (@modelcontextprotocol/inspector)..." -ForegroundColor Yellow
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & npm install -g @modelcontextprotocol/inspector@0.22.0 2>&1 | Out-Null
    } finally {
        $ErrorActionPreference = $prev
    }
    if (-not (Get-Command mcp-inspector -ErrorAction SilentlyContinue)) {
        Write-Host "ERROR: mcp-inspector install failed. Run: npm install -g @modelcontextprotocol/inspector" -ForegroundColor Red
        exit 1
    }
    Write-Host "MCP Inspector installed." -ForegroundColor Green
}

function Start-McpInspectorBackground {
    param(
        [string]$Name,
        [string]$ClientPort,
        [string]$ServerPort,
        [string]$AuthToken,
        [string]$LogFile
    )

    $logDir = Split-Path $LogFile -Parent
    if ($logDir -and -not (Test-Path $logDir)) {
        New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    }

    $errFile = "$LogFile.err"
    $deployEsc = $Script:DeployRoot.Replace("'", "''")
    $tokenEsc = $AuthToken.Replace("'", "''")
    $cmd = @"
`$env:CLIENT_PORT = '$ClientPort'
`$env:SERVER_PORT = '$ServerPort'
`$env:MCP_PROXY_AUTH_TOKEN = '$tokenEsc'
`$env:MCP_AUTO_OPEN_ENABLED = 'false'
Set-Location '$deployEsc'
mcp-inspector
"@

    $proc = Start-Process -FilePath "powershell.exe" `
        -ArgumentList @("-NoProfile", "-WindowStyle", "Hidden", "-Command", $cmd) `
        -WorkingDirectory $Script:DeployRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $LogFile `
        -RedirectStandardError $errFile `
        -PassThru

    return [ordered]@{
        name    = $Name
        pid     = $proc.Id
        logFile = $LogFile
    }
}

function Open-McpInspectorBrowsers {
    param(
        [hashtable[]]$Instances,
        [int]$WaitSeconds = 10
    )
    Write-Host "Waiting ${WaitSeconds}s for Inspector to start..." -ForegroundColor DarkGray
    Start-Sleep -Seconds $WaitSeconds
    foreach ($inst in $Instances) {
        Start-Process $inst.Url
        Write-Host "Opened browser: $($inst.Label) -> $($inst.Url)" -ForegroundColor Green
        Start-Sleep -Seconds 1
    }
}

function Get-DemoServicesPidFile {
    return Join-DemoPath "logs\demo-services.json"
}

function Read-DemoServicesState {
    $file = Get-DemoServicesPidFile
    if (-not (Test-Path $file)) {
        return $null
    }
    try {
        return Get-Content -Path $file -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        return $null
    }
}

function Save-DemoServicesState {
    param(
        [array]$Processes,
        [string]$DeployRoot
    )
    $file = Get-DemoServicesPidFile
    $dir = Split-Path $file -Parent
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    $state = [ordered]@{
        startedAt  = (Get-Date).ToUniversalTime().ToString('o')
        deployRoot = $DeployRoot
        processes  = @($Processes)
    }
    ($state | ConvertTo-Json -Depth 4) | Set-Content -Path $file -Encoding UTF8
}

function Get-RunningDemoProcesses {
    param($State)
    if ($null -eq $State -or $null -eq $State.processes) {
        return @()
    }
    $running = @()
    foreach ($item in $State.processes) {
        $proc = Get-Process -Id $item.pid -ErrorAction SilentlyContinue
        if ($null -ne $proc) {
            $running += $item
        }
    }
    return $running
}

function Test-DemoServicesRunning {
    $state = Read-DemoServicesState
    if ($null -eq $state) {
        return $false
    }
    return (@(Get-RunningDemoProcesses $state)).Count -gt 0
}

function Start-DemoBackgroundProcess {
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory,
        [string]$LogFile
    )

    $logDir = Split-Path $LogFile -Parent
    if ($logDir -and -not (Test-Path $logDir)) {
        New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    }

    $errFile = "$LogFile.err"
    if (Test-Path $LogFile) {
        Add-Content -Path $LogFile -Value "`n--- restart $(Get-Date -Format o) ---`n" -Encoding UTF8
    }

    $proc = Start-Process -FilePath $FilePath `
        -ArgumentList $ArgumentList `
        -WorkingDirectory $WorkingDirectory `
        -WindowStyle Hidden `
        -RedirectStandardOutput $LogFile `
        -RedirectStandardError $errFile `
        -PassThru

    return [ordered]@{
        name    = $Name
        pid     = $proc.Id
        logFile = $LogFile
    }
}

function Stop-DemoProcessTree {
    param([int]$ProcessId)
    $proc = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($null -eq $proc) {
        return
    }
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try {
        & taskkill.exe /PID $ProcessId /T /F 2>&1 | Out-Null
    } finally {
        $ErrorActionPreference = $prev
    }
}

function Stop-DemoProcessesByPrefix {
    param(
        [string]$NamePrefix,
        [switch]$Quiet
    )
    $state = Read-DemoServicesState
    if ($null -eq $state -or $null -eq $state.processes) {
        return @()
    }
    $remaining = @()
    foreach ($item in $state.processes) {
        if ($item.name -like "${NamePrefix}*") {
            $proc = Get-Process -Id $item.pid -ErrorAction SilentlyContinue
            if ($null -ne $proc) {
                if (-not $Quiet) {
                    Write-Host "Stopping $($item.name) (PID $($item.pid))..." -ForegroundColor DarkGray
                }
                Stop-DemoProcessTree -ProcessId $item.pid
            } elseif (-not $Quiet) {
                Write-Host "Skip $($item.name) (PID $($item.pid) already exited)" -ForegroundColor DarkGray
            }
        } else {
            $remaining += $item
        }
    }
    return $remaining
}

function Merge-DemoServiceProcesses {
    param(
        [array]$NewProcesses,
        [string]$DeployRoot
    )
    $state = Read-DemoServicesState
    $existing = @()
    if ($null -ne $state -and $null -ne $state.processes) {
        $existing = @($state.processes)
    }
    $merged = @($existing) + @($NewProcesses)
    Save-DemoServicesState -Processes $merged -DeployRoot $DeployRoot
}

function Stop-DemoServices {
    param(
        [switch]$Quiet
    )

    $state = Read-DemoServicesState
    $stopped = 0
    $missing = 0

    if ($null -ne $state -and $null -ne $state.processes) {
        foreach ($item in $state.processes) {
            $proc = Get-Process -Id $item.pid -ErrorAction SilentlyContinue
            if ($null -eq $proc) {
                $missing++
                continue
            }
            if (-not $Quiet) {
                Write-Host "Stopping $($item.name) (PID $($item.pid))..." -ForegroundColor DarkGray
            }
            Stop-DemoProcessTree -ProcessId $item.pid
            $stopped++
        }
    }

    $pidFile = Get-DemoServicesPidFile
    if (Test-Path $pidFile) {
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    }

    if (-not $Quiet) {
        if ($stopped -eq 0 -and $missing -eq 0) {
            Write-Host "No demo services were registered (nothing to stop)." -ForegroundColor Yellow
        } else {
            Write-Host "Stopped $stopped process(es)." -ForegroundColor Green
            if ($missing -gt 0) {
                Write-Host "$missing process(es) already exited." -ForegroundColor DarkGray
            }
        }
    }

    return $stopped
}
