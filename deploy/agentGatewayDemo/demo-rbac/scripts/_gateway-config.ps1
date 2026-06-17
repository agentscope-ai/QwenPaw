# AgentGateway config state + restart helpers (demo-rbac).

function Get-GatewayConfigStateFile {
    return Join-DemoPath "logs\gateway-config.state"
}

function Get-GatewayConfigFileName {
    param(
        [string]$Default = "agentgateway-rbac.yaml"
    )
    $stateFile = Get-GatewayConfigStateFile
    if (-not (Test-Path $stateFile)) {
        return $Default
    }
    $name = (Get-Content -Path $stateFile -Raw -Encoding UTF8).Trim()
    if ([string]::IsNullOrWhiteSpace($name)) {
        return $Default
    }
    return $name
}

function Get-GatewayConfigPath {
    param(
        [string]$Default = "agentgateway-rbac.yaml"
    )
    $fileName = Get-GatewayConfigFileName -Default $Default
    return Join-DemoPath ("config\" + $fileName)
}

function Set-GatewayConfigFileName {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ConfigFileName
    )
    $stateFile = Get-GatewayConfigStateFile
    $dir = Split-Path $stateFile -Parent
    if ($dir -and -not (Test-Path $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    Set-Content -Path $stateFile -Value $ConfigFileName -Encoding UTF8 -NoNewline
}

function Restart-AgentGateway {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ConfigPath
    )

    $AgwExe = Assert-AgentGateway
    $gatewayLog = Join-DemoPath "logs\gateway-access.log"

    $remaining = Stop-DemoProcessesByPrefix -NamePrefix "agentgateway" -Quiet
    Start-Sleep -Seconds 1

    $proc = Start-DemoBackgroundProcess `
        -Name "agentgateway" `
        -FilePath $AgwExe `
        -ArgumentList @("-f", $ConfigPath) `
        -WorkingDirectory $Script:DeployRoot `
        -LogFile $gatewayLog

    Save-DemoServicesState -Processes (@($remaining) + @($proc)) -DeployRoot $Script:DeployRoot
    return $proc
}
