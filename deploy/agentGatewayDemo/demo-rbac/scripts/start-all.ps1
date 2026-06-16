# Start all RBAC demo services in background (no popup windows).
# Run from DeployRoot:  .\demo-rbac\scripts\start-all.ps1
# Stop services:        .\demo-rbac\scripts\stop-all.ps1
#
# By default each start resets gateway to phase A (agentgateway-rbac.yaml).
# Use -KeepPolicy to keep gateway-config.state (e.g. stay on downgraded config).

param(
    [switch]$Restart,
    [switch]$KeepPolicy
)

. "$PSScriptRoot\_common.ps1"
. "$PSScriptRoot\_gateway-config.ps1"

$PhaseAConfig = "agentgateway-rbac.yaml"
$PhaseBConfig = "agentgateway-rbac-downgraded.yaml"

$ErrorActionPreference = "Stop"
Set-DeployLocation
Install-DemoPythonDeps
$AgwExe = Assert-AgentGateway

if (Test-DemoServicesRunning) {
    if ($Restart) {
        Write-Host "Restarting demo services..." -ForegroundColor Yellow
        Stop-DemoServices | Out-Null
        Start-Sleep -Seconds 1
    } else {
        Write-Host "Demo services already running in background." -ForegroundColor Yellow
        Write-Host "  Active gateway config: $(Get-GatewayConfigFileName)" -ForegroundColor DarkGray
        Write-Host "  Stop:    .\demo-rbac\scripts\stop-all.ps1" -ForegroundColor DarkGray
        Write-Host "  Restart: .\demo-rbac\scripts\start-all.ps1 -Restart" -ForegroundColor DarkGray
        exit 0
    }
}

if (-not $KeepPolicy) {
    Set-GatewayConfigFileName -ConfigFileName $PhaseAConfig
    Write-Host "Gateway policy reset to phase A ($PhaseAConfig)" -ForegroundColor DarkGray
} else {
    Write-Host "Keeping gateway policy from state: $(Get-GatewayConfigFileName)" -ForegroundColor DarkGray
}

$hrServer = Join-DemoPath "mcp-hr\server.py"
$forumServer = Join-DemoPath "mcp-forum\server.py"
$agwConfig = Get-GatewayConfigPath
$activeConfigName = Get-GatewayConfigFileName
$gatewayLog = Join-DemoPath "logs\gateway-access.log"
$watcherScript = Join-DemoPath "monitor\gateway_error_watcher.py"
$watcherLog = Join-DemoPath "logs\gateway-error-watcher.log"
$hrLog = Join-DemoPath "logs\mcp-hr.log"
$forumLog = Join-DemoPath "logs\mcp-forum.log"

Write-Host ""
Write-Host "=== RBAC Demo - Starting services (background) ===" -ForegroundColor Green
Write-Host "DeployRoot: $Script:DeployRoot"
Write-Host ""

$processes = @()

$processes += Start-DemoBackgroundProcess `
    -Name "mcp-hr" `
    -FilePath "python" `
    -ArgumentList @($hrServer) `
    -WorkingDirectory $Script:DeployRoot `
    -LogFile $hrLog
Start-Sleep -Seconds 1

$processes += Start-DemoBackgroundProcess `
    -Name "mcp-forum" `
    -FilePath "python" `
    -ArgumentList @($forumServer) `
    -WorkingDirectory $Script:DeployRoot `
    -LogFile $forumLog
Start-Sleep -Seconds 1

$processes += Start-DemoBackgroundProcess `
    -Name "agentgateway" `
    -FilePath $AgwExe `
    -ArgumentList @("-f", $agwConfig) `
    -WorkingDirectory $Script:DeployRoot `
    -LogFile $gatewayLog
Start-Sleep -Seconds 2

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
Start-Sleep -Seconds 1

Save-DemoServicesState -Processes $processes -DeployRoot $Script:DeployRoot

Write-Host "Started 4 background services:" -ForegroundColor Green
foreach ($p in $processes) {
    Write-Host "  $($p.name)  PID $($p.pid)  log: $($p.logFile)" -ForegroundColor DarkGray
}
$phaseLabel = if ($activeConfigName -eq $PhaseAConfig) { "phase A (5 tools for employee)" } elseif ($activeConfigName -eq $PhaseBConfig) { "phase B (2 tools for employee)" } else { "custom" }
Write-Host ""
Write-Host "Gateway config: $activeConfigName — $phaseLabel" -ForegroundColor Cyan
Write-Host ""
Write-Host "Stop all (MCP + Gateway + Error Watcher + Inspectors):  .\demo-rbac\scripts\stop-all.ps1" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. Dual Inspector: .\demo-rbac\scripts\open-dual-inspector.ps1"
Write-Host "  2. Helper page:     open .\demo-rbac\inspector-helper.html"
Write-Host "  3. Auto demo:       .\demo-rbac\scripts\run-demo.ps1"
Write-Host "  4. Debug trace:     .\demo-rbac\scripts\start-trace.ps1"
Write-Host "  5. Auth deny audit: .\demo-rbac\scripts\audit-auth-deny.ps1 -RunAttack"
Write-Host "  6. Auth deny viewer: .\demo-rbac\scripts\show-auth-deny.ps1"
Write-Host "  8. Downgrade policy: .\demo-rbac\scripts\downgrade-employee.ps1"
Write-Host "  9. Two-tool probe:   .\demo-rbac\scripts\call-forum-hr.ps1"
Write-Host " 10. Admin Console:   http://localhost:15000/ui"
