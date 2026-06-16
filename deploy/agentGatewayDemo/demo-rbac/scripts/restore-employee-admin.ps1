# Restore gateway phase-A policy (role-based manager access).
# Run from DeployRoot:  .\demo-rbac\scripts\restore-employee-admin.ps1

. "$PSScriptRoot\_common.ps1"
. "$PSScriptRoot\_gateway-config.ps1"

$ErrorActionPreference = "Stop"
Set-DeployLocation

$phaseName = "agentgateway-rbac.yaml"
$phasePath = Join-DemoPath ("config\" + $phaseName)

if (-not (Test-Path $phasePath)) {
    Write-Host "ERROR: missing config $phasePath" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=== Gateway policy restore (phase A) ===" -ForegroundColor Green
Write-Host "Config: $phaseName"
Write-Host ""

Set-GatewayConfigFileName -ConfigFileName $phaseName
$proc = Restart-AgentGateway -ConfigPath $phasePath
Start-Sleep -Seconds 2

Write-Host "AgentGateway restarted  PID $($proc.pid)" -ForegroundColor Green
Write-Host "employeeQwenpaw with manager JWT -> 5 tools again (Reconnect MCP)" -ForegroundColor DarkGray
