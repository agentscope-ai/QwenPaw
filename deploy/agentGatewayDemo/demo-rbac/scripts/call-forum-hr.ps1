# Call forum_list_posts + hr_get_employee with employeeQwenpaw token.
# Phase A: both succeed. Phase B (after downgrade-employee.ps1): HR blocked.
# Run from DeployRoot:  .\demo-rbac\scripts\call-forum-hr.ps1

. "$PSScriptRoot\_common.ps1"

$ErrorActionPreference = "Stop"
Set-DeployLocation
Install-DemoPythonDeps

$client = Join-DemoPath "clients\demo_forum_hr.py"
$configName = "unknown"
try {
    . "$PSScriptRoot\_gateway-config.ps1"
    $configName = Get-GatewayConfigFileName
} catch {
    # _gateway-config optional if only running client
}

Write-Host ""
Write-Host "=== forum_list_posts + hr_get_employee (employeeQwenpaw) ===" -ForegroundColor Green
Write-Host "Gateway config: $configName" -ForegroundColor DarkGray
Write-Host ""

python $client @args
