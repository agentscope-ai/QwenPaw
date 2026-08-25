# Automated story: open direct access -> lock backends -> four gateway checks.
# Run from DeployRoot:  .\demo-rbac\scripts\run-gateway-demo.ps1

. "$PSScriptRoot\_common.ps1"

$ErrorActionPreference = "Stop"
Set-DeployLocation
Install-DemoPythonDeps

$client = Join-DemoPath "clients\demo_unified.py"
$startOpen = Join-DemoPath "scripts\start-open-demo.ps1"
$enableGw = Join-DemoPath "scripts\enable-gateway.ps1"

function Invoke-UnifiedPhase {
    param(
        [string]$Phase,
        [string]$Title
    )
    Write-Host ""
    Write-Host "--- $Title ---" -ForegroundColor Cyan
    & python $client --phase $Phase | Out-Host
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Failed phase: $Phase (exit $LASTEXITCODE)" -ForegroundColor Red
        return $false
    }
    return $true
}

Write-Host "=== Unified Gateway Demo - automated story ===" -ForegroundColor Green
Write-Host "DeployRoot: $Script:DeployRoot"
Write-Host ""

& $startOpen -Restart
if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to start open MCP backends." -ForegroundColor Red
    exit 1
}

$ok = $true
if (-not (Invoke-UnifiedPhase -Phase "open" -Title "1/5 anonymousAgent direct to three MCPs (expect success)")) {
    $ok = $false
}

& $enableGw
if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to enable AgentGateway." -ForegroundColor Red
    exit 1
}
Start-Sleep -Seconds 2

if (-not (Invoke-UnifiedPhase -Phase "bypass" -Title "2/5 bypass gateway, hit backends directly (expect deny)")) { $ok = $false }
if (-not (Invoke-UnifiedPhase -Phase "no-token" -Title "3/5 via gateway, no JWT (expect deny)")) { $ok = $false }
if (-not (Invoke-UnifiedPhase -Phase "forged" -Title "4/5 via gateway, forged JWT (expect deny)")) { $ok = $false }
if (-not (Invoke-UnifiedPhase -Phase "valid" -Title "5/5 via gateway, valid JWT (expect success)")) { $ok = $false }

Write-Host ""
if ($ok) {
    Write-Host "Done: open chaos vs gateway control verified." -ForegroundColor Green
    Write-Host "Access log: .\demo-rbac\logs\gateway-access.log" -ForegroundColor DarkGray
    exit 0
}

Write-Host "Failed: inspect demo-rbac\logs\ and retry start-open-demo / enable-gateway." -ForegroundColor Red
exit 1
