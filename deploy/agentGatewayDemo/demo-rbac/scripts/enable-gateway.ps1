# Phase B: lock MCP backends behind gateway-only credentials and start AgentGateway.
# Run from DeployRoot:  .\demo-rbac\scripts\enable-gateway.ps1

. "$PSScriptRoot\_common.ps1"
. "$PSScriptRoot\_gateway-config.ps1"
. "$PSScriptRoot\_backend-tokens.ps1"
. "$PSScriptRoot\_unified-mcp.ps1"

$ErrorActionPreference = "Stop"
Set-DeployLocation
Install-DemoPythonDeps
$AgwExe = Assert-AgentGateway

$UnifiedConfig = "agentgateway-unified.yaml"
$UnifiedPath = Join-DemoPath ("config\" + $UnifiedConfig)
if (-not (Test-Path $UnifiedPath)) {
    Write-Host "ERROR: missing $UnifiedPath" -ForegroundColor Red
    exit 1
}

if (Test-DemoServicesRunning) {
    Write-Host "Stopping existing demo services before enabling gateway..." -ForegroundColor Yellow
    Stop-DemoServices | Out-Null
    Start-Sleep -Seconds 1
}

Stop-DemoPortListeners
Start-Sleep -Seconds 1

Ensure-BackendTokens
Show-BackendTokenStatus
& "$PSScriptRoot\print-qwenpaw-gateway-json.ps1" | Out-Null
Set-GatewayConfigFileName -ConfigFileName $UnifiedConfig

$gatewayLog = Join-DemoPath "logs\gateway-access.log"
$watcherScript = Join-DemoPath "monitor\gateway_error_watcher.py"
$watcherLog = Join-DemoPath "logs\gateway-error-watcher.log"

Write-Host ""
Write-Host "=== Unified MCP Demo - Phase B (gateway required) ===" -ForegroundColor Green
Write-Host "DeployRoot: $Script:DeployRoot"
Write-Host "Gateway config: $UnifiedConfig"
Write-Host ""

$processes = Start-UnifiedMcpServers -AuthMode "protected"
if (-not (Wait-UnifiedMcpReady)) {
    Write-Host "ERROR: protected MCP backends failed to listen. Check logs." -ForegroundColor Red
    exit 1
}

$processes += Start-DemoBackgroundProcess `
    -Name "agentgateway" `
    -FilePath $AgwExe `
    -ArgumentList @("-f", $UnifiedPath) `
    -WorkingDirectory $Script:DeployRoot `
    -LogFile $gatewayLog
Start-Sleep -Seconds 2

if (-not (Wait-DemoPort -Port 3000 -TimeoutSeconds 20)) {
    Write-Host "ERROR: AgentGateway port 3000 not listening. See $gatewayLog" -ForegroundColor Red
    exit 1
}

$watcherStopFile = Join-DemoPath "logs\gateway-error-watcher.stop"
if (Test-Path $watcherStopFile) {
    Remove-Item $watcherStopFile -Force -ErrorAction SilentlyContinue
}

$processes += Start-DemoBackgroundProcess `
    -Name "gateway-error-watcher" `
    -FilePath "python" `
    -ArgumentList @($watcherScript) `
    -WorkingDirectory $Script:DeployRoot `
    -LogFile $watcherLog

Save-DemoServicesState -Processes $processes -DeployRoot $Script:DeployRoot

Write-Host "Started protected MCP backends + AgentGateway:" -ForegroundColor Green
foreach ($p in $processes) {
    Write-Host "  $($p.name)  PID $($p.pid)  log: $($p.logFile)" -ForegroundColor DarkGray
}
Write-Host ""
Write-Host "Client entry:  http://localhost:3000/mcp  (JWT required)" -ForegroundColor Cyan
Write-Host "Direct :9001/:9002/:9003 now reject requests without the gateway credential."
Write-Host ""
Write-Host "Next:" -ForegroundColor Yellow
Write-Host "  1. QwenPaw full flow: see ..\QwenPaw_demo.md"
Write-Host "  2. Keep open-clients first (direct should fail), then:"
Write-Host "       gateway-no-token.json -> gateway-forged-client.json -> gateway-client.json"
Write-Host "  3. Probe:   python .\demo-rbac\clients\demo_unified.py --phase bypass|no-token|forged|valid"
Write-Host "  4. Auto:    .\demo-rbac\scripts\run-gateway-demo.ps1"
Write-Host "  5. Stop:    .\demo-rbac\scripts\stop-all.ps1"
