# Shared start helpers for the unified-gateway demo (Forum + HR + Finance).

function Start-UnifiedMcpServers {
    param(
        [ValidateSet("open", "protected")]
        [string]$AuthMode
    )

    $hrLog = Join-DemoPath "logs\mcp-hr.log"
    $forumLog = Join-DemoPath "logs\mcp-forum.log"
    $financeLog = Join-DemoPath "logs\mcp-finance.log"

    $processes = @()

    $hrArgs = @((Join-DemoPath "mcp-hr\server.py"), "--auth-mode", $AuthMode, "--gateway-token-env", "HR_GATEWAY_TOKEN")
    $forumArgs = @((Join-DemoPath "mcp-forum\server.py"), "--auth-mode", $AuthMode, "--gateway-token-env", "FORUM_GATEWAY_TOKEN")
    $financeArgs = @((Join-DemoPath "mcp-finance\server.py"), "--auth-mode", $AuthMode, "--gateway-token-env", "FINANCE_GATEWAY_TOKEN")

    $processes += Start-DemoBackgroundProcess `
        -Name "mcp-hr" `
        -FilePath "python" `
        -ArgumentList $hrArgs `
        -WorkingDirectory $Script:DeployRoot `
        -LogFile $hrLog
    Start-Sleep -Seconds 1

    $processes += Start-DemoBackgroundProcess `
        -Name "mcp-forum" `
        -FilePath "python" `
        -ArgumentList $forumArgs `
        -WorkingDirectory $Script:DeployRoot `
        -LogFile $forumLog
    Start-Sleep -Seconds 1

    $processes += Start-DemoBackgroundProcess `
        -Name "mcp-finance" `
        -FilePath "python" `
        -ArgumentList $financeArgs `
        -WorkingDirectory $Script:DeployRoot `
        -LogFile $financeLog

    return $processes
}

function Wait-UnifiedMcpReady {
    param([int]$TimeoutSeconds = 25)

    $ok = $true
    foreach ($port in @(9001, 9002, 9003)) {
        if (-not (Wait-DemoPort -Port $port -TimeoutSeconds $TimeoutSeconds)) {
            Write-Host "WARN: MCP port $port not listening yet" -ForegroundColor Yellow
            $ok = $false
        }
    }
    return $ok
}