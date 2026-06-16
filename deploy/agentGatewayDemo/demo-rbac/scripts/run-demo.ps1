# RBAC automated demo — role downgrade via gateway policy (token unchanged)
. "$PSScriptRoot\_common.ps1"
. "$PSScriptRoot\_gateway-config.ps1"

$ErrorActionPreference = "Stop"
Set-DeployLocation

$guestClient = Join-DemoPath "clients\demo_guest.py"
$employeeClient = Join-DemoPath "clients\demo_employee.py"
$managerClient = Join-DemoPath "clients\demo_manager.py"
$downgradeScript = Join-DemoPath "scripts\downgrade-employee.ps1"

Write-Host "=== RBAC Demo — Gateway Downgrade Story ===" -ForegroundColor Green
Write-Host "DeployRoot: $Script:DeployRoot"
Write-Host "Active gateway config: $(Get-GatewayConfigFileName)" -ForegroundColor DarkGray
Write-Host ""

# Ensure phase A before admin phase demo
if ((Get-GatewayConfigFileName) -ne "agentgateway-rbac.yaml") {
    Write-Host "Restoring phase A config for first act..." -ForegroundColor Yellow
    & (Join-DemoPath "scripts\restore-employee-admin.ps1")
    Start-Sleep -Seconds 2
}

Write-Host "--- 1/5 guest (no token) ---" -ForegroundColor Cyan
python $guestClient
$guestCode = $LASTEXITCODE

Write-Host ""
Write-Host "--- 2/5 employeeQwenpaw phase A (admin JWT, 5 tools) ---" -ForegroundColor Cyan
python $employeeClient --phase admin
$adminCode = $LASTEXITCODE

Write-Host ""
Write-Host "--- 3/5 gateway downgrade (policy only, token unchanged) ---" -ForegroundColor Yellow
& $downgradeScript
Start-Sleep -Seconds 2

Write-Host ""
Write-Host "--- 4/5 employeeQwenpaw phase B (same token, HR attack) ---" -ForegroundColor Cyan
python $employeeClient --phase downgraded
$downgradedCode = $LASTEXITCODE

Write-Host ""
Write-Host "--- 5/5 managerQwenpaw (still full admin) ---" -ForegroundColor Cyan
python $managerClient

Write-Host ""
if ($guestCode -eq 0 -and $adminCode -eq 0 -and $downgradedCode -eq 0) {
    Write-Host "Done: downgrade story verified; same employee token blocked for HR after policy change" -ForegroundColor Green
} else {
    Write-Host "Failed: run .\demo-rbac\scripts\start-all.ps1 -Restart first" -ForegroundColor Red
}
