# Phase A: start Forum / HR / Finance MCP with no authentication (no gateway).
# Run from DeployRoot:  .\demo-rbac\scripts\start-open-demo.ps1

param(
    [switch]$Restart
)

. "$PSScriptRoot\_common.ps1"
. "$PSScriptRoot\_unified-mcp.ps1"

$ErrorActionPreference = "Stop"
Set-DeployLocation
Install-DemoPythonDeps

if (Test-DemoServicesRunning) {
    if ($Restart) {
        Write-Host "Restarting demo services..." -ForegroundColor Yellow
        Stop-DemoServices | Out-Null
        Start-Sleep -Seconds 1
    } else {
        Write-Host "Demo services already running. Use -Restart or stop-all.ps1 first." -ForegroundColor Yellow
        exit 0
    }
}

Stop-DemoPortListeners
Start-Sleep -Seconds 1

Write-Host ""
Write-Host "=== Unified MCP Demo - Phase A (open, no gateway) ===" -ForegroundColor Green
Write-Host "DeployRoot: $Script:DeployRoot"
Write-Host ""

$processes = Start-UnifiedMcpServers -AuthMode "open"
Save-DemoServicesState -Processes $processes -DeployRoot $Script:DeployRoot

if (-not (Wait-UnifiedMcpReady)) {
    Write-Host "ERROR: one or more MCP ports failed to open. Check logs under demo-rbac\logs\" -ForegroundColor Red
    exit 1
}

Write-Host "Started 3 unprotected MCP servers:" -ForegroundColor Green
foreach ($p in $processes) {
    Write-Host "  $($p.name)  PID $($p.pid)  log: $($p.logFile)" -ForegroundColor DarkGray
}
Write-Host ""
Write-Host "Direct URLs (no Authorization required):" -ForegroundColor Cyan
Write-Host "  HR      http://127.0.0.1:9001/mcp"
Write-Host "  Forum   http://127.0.0.1:9002/mcp"
Write-Host "  Finance http://127.0.0.1:9003/mcp"
Write-Host ""
Write-Host "Next:" -ForegroundColor Yellow
Write-Host "  1. QwenPaw: import demo-rbac\qwenpaw\open-clients.json"
Write-Host "  2. Probe:   python .\demo-rbac\clients\demo_unified.py --phase open"
Write-Host "  3. Enable gateway: .\demo-rbac\scripts\enable-gateway.ps1"
Write-Host "  4. Stop:    .\demo-rbac\scripts\stop-all.ps1"
