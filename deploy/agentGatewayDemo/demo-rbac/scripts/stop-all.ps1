# Stop RBAC demo background services (MCP + AgentGateway + Inspectors).
# Run from DeployRoot:  .\demo-rbac\scripts\stop-all.ps1

. "$PSScriptRoot\_common.ps1"

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "=== RBAC Demo - Stop services ===" -ForegroundColor Cyan
Write-Host "DeployRoot: $Script:DeployRoot"
Write-Host ""

$watcherStopFile = Join-DemoPath "logs\gateway-error-watcher.stop"
$watcherStopDir = Split-Path $watcherStopFile -Parent
if ($watcherStopDir -and -not (Test-Path $watcherStopDir)) {
    New-Item -ItemType Directory -Force -Path $watcherStopDir | Out-Null
}
"" | Set-Content -Path $watcherStopFile -Encoding UTF8

Stop-DemoServices

Write-Host ""
Write-Host "All background services stopped (MCP, Gateway, Error Watcher, Inspectors)." -ForegroundColor Green
