# Start mock Security Center in the foreground (prints received events to this terminal).
# Run from DeployRoot:  .\demo-rbac\scripts\start-mock-security-center.ps1
#
# Typical integration test flow:
#   Terminal 1: .\demo-rbac\scripts\start-mock-security-center.ps1
#   Terminal 2: .\demo-rbac\scripts\start-all.ps1 -Restart
#   Terminal 2: .\demo-rbac\scripts\run-demo.ps1

. "$PSScriptRoot\_common.ps1"

$ErrorActionPreference = "Stop"
Set-DeployLocation
Install-DemoPythonDeps

$mockScript = Join-DemoPath "monitor\mock_security_center.py"
$eventLog = Join-DemoPath "logs\mock-security-center.events.jsonl"

$listener = Get-NetTCPConnection -LocalPort 8091 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($listener) {
    $owner = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
    $ownerName = if ($owner) { $owner.ProcessName } else { "unknown" }
    Write-Host ""
    Write-Host "WARN: port 8091 is already in use (PID $($listener.OwningProcess), $ownerName)." -ForegroundColor Yellow
    Write-Host "      Stop that process first, otherwise this window will NOT receive events." -ForegroundColor Yellow
    Write-Host "      Example: taskkill /PID $($listener.OwningProcess) /F" -ForegroundColor DarkGray
    Write-Host ""
}

Write-Host ""
Write-Host "=== Mock Security Center (foreground) ===" -ForegroundColor Green
Write-Host "Endpoint: http://127.0.0.1:8091/security-center/v1/events"
Write-Host "Backup log: $eventLog"
Write-Host "Press Ctrl+C to stop."
Write-Host ""

# -u: unbuffered stdout/stderr for immediate console output in PowerShell.
python -u $mockScript --event-log-file $eventLog
