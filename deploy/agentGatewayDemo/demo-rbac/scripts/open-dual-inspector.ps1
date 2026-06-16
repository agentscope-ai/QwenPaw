# Dual MCP Inspector launcher (background, no popup windows)
. "$PSScriptRoot\_common.ps1"

$ErrorActionPreference = "Stop"
$Helper = Join-DemoPath "inspector-helper.html"
$tokEmployee = Join-DemoPath "jwt\employeeQwenpaw.key"
$tokManager = Join-DemoPath "jwt\managerQwenpaw.key"

$LeftClientPort = "6274"
$LeftServerPort = "6277"
$LeftAuthToken = "rbac-employee-inspector"
$GatewayMcpUrl = "http://localhost:3000/mcp"
$GatewayMcpUrlEncoded = [uri]::EscapeDataString($GatewayMcpUrl)

$LeftBrowserUrl = "http://localhost:${LeftClientPort}/?MCP_PROXY_AUTH_TOKEN=${LeftAuthToken}&transport=streamable-http&serverUrl=${GatewayMcpUrlEncoded}"

$RightClientPort = "6275"
$RightServerPort = "6278"
$RightAuthToken = "rbac-manager-inspector"
$RightBrowserUrl = "http://localhost:${RightClientPort}/?MCP_PROXY_PORT=${RightServerPort}&MCP_PROXY_AUTH_TOKEN=${RightAuthToken}&transport=streamable-http&serverUrl=${GatewayMcpUrlEncoded}"

$InspectorLogEmployee = Join-DemoPath "logs\inspector-employee.log"
$InspectorLogManager = Join-DemoPath "logs\inspector-manager.log"

Write-Host "=== Dual MCP Inspector — Role Downgrade Demo ===" -ForegroundColor Green
Write-Host ""
Write-Host "Left  - employeeQwenpaw token (same before/after downgrade)"
Write-Host "Right - managerQwenpaw token (always full admin)"
Write-Host ""
Write-Host "Phase A: employee sees 5 tools | Phase B after downgrade-employee.ps1: 2 tools"
Write-Host ""
Write-Host "Inspector UI (browser tabs will open):" -ForegroundColor Yellow
Write-Host "  Employee: $LeftBrowserUrl"
Write-Host "  Manager : $RightBrowserUrl"
Write-Host ""

Ensure-McpInspector

Write-Host "Restarting background Inspector processes..." -ForegroundColor DarkGray
$remaining = Stop-DemoProcessesByPrefix -NamePrefix "inspector-" -Quiet

$inspectors = @()

Write-Host "Starting Inspector (employeeQwenpaw)..." -ForegroundColor Green
$inspectors += Start-McpInspectorBackground `
    -Name "inspector-employee" `
    -ClientPort $LeftClientPort `
    -ServerPort $LeftServerPort `
    -AuthToken $LeftAuthToken `
    -LogFile $InspectorLogEmployee
Start-Sleep -Seconds 2

Write-Host "Starting Inspector (managerQwenpaw)..." -ForegroundColor Green
$inspectors += Start-McpInspectorBackground `
    -Name "inspector-manager" `
    -ClientPort $RightClientPort `
    -ServerPort $RightServerPort `
    -AuthToken $RightAuthToken `
    -LogFile $InspectorLogManager

Save-DemoServicesState -Processes (@($remaining) + @($inspectors)) -DeployRoot $Script:DeployRoot

foreach ($p in $inspectors) {
    Write-Host "  $($p.name)  PID $($p.pid)  log: $($p.logFile)" -ForegroundColor DarkGray
}

Open-McpInspectorBrowsers @(
    @{ Label = "Employee"; Url = $LeftBrowserUrl },
    @{ Label = "Manager"; Url = $RightBrowserUrl }
)

if (Test-Path $Helper) {
    Start-Process $Helper
    Write-Host "Opened inspector-helper.html" -ForegroundColor Green
}

Write-Host ""
Write-Host "Inspectors run in background. Stop all: .\demo-rbac\scripts\stop-all.ps1" -ForegroundColor Cyan
Write-Host ""
Write-Host "Demo checklist:" -ForegroundColor Yellow
Write-Host "  1. No token -> List Tools = 1 (forum_list_posts)"
Write-Host "  2. Employee token -> List Tools = 2 (+ forum_create_post)"
Write-Host "  3. Manager token -> List Tools = 5"
Write-Host "  4. Employee token: hr_get_employee -> BLOCKED | Manager: OK"
