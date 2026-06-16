# Switch gateway to downgraded policy (employeeQwenpaw sub-based allow list).
# Token is NOT changed — employees may still use backed-up admin JWT.
# Run from DeployRoot:  .\demo-rbac\scripts\downgrade-employee.ps1

. "$PSScriptRoot\_common.ps1"
. "$PSScriptRoot\_gateway-config.ps1"

$ErrorActionPreference = "Stop"
Set-DeployLocation

$downgradedName = "agentgateway-rbac-downgraded.yaml"
$downgradedPath = Join-DemoPath ("config\" + $downgradedName)

if (-not (Test-Path $downgradedPath)) {
    Write-Host "ERROR: missing config $downgradedPath" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=== Gateway policy downgrade (employeeQwenpaw) ===" -ForegroundColor Yellow
Write-Host "Config: $downgradedName"
Write-Host "Token:  unchanged (JWT may still contain manager role)"
Write-Host ""

Set-GatewayConfigFileName -ConfigFileName $downgradedName
$proc = Restart-AgentGateway -ConfigPath $downgradedPath
Start-Sleep -Seconds 2

Write-Host "AgentGateway restarted  PID $($proc.pid)" -ForegroundColor Green
Write-Host ""
Write-Host "Next:" -ForegroundColor Cyan
Write-Host "  - QwenPaw / Inspector: same Token, Reconnect MCP"
Write-Host "  - employeeQwenpaw List Tools -> 2 (forum only)"
Write-Host "  - hr_get_employee with same Token -> denied + security event"
Write-Host "  - managerQwenpaw Token still has 5 tools"
Write-Host ""
Write-Host "Restore phase A: .\demo-rbac\scripts\restore-employee-admin.ps1" -ForegroundColor DarkGray
