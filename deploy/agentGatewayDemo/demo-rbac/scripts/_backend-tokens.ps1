# Generate / load per-backend gateway credentials (not committed).

$Script:BackendTokenMap = [ordered]@{
    hr      = @{ EnvName = "HR_GATEWAY_TOKEN";      FileName = "hr.token" }
    forum   = @{ EnvName = "FORUM_GATEWAY_TOKEN";   FileName = "forum.token" }
    finance = @{ EnvName = "FINANCE_GATEWAY_TOKEN"; FileName = "finance.token" }
}

function Get-BackendSecretsDir {
    return Join-DemoPath "secrets"
}

function New-BackendTokenValue {
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return [Convert]::ToBase64String($bytes)
}

function Ensure-BackendTokens {
    $dir = Get-BackendSecretsDir
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }

    foreach ($svc in $Script:BackendTokenMap.Keys) {
        $meta = $Script:BackendTokenMap[$svc]
        $file = Join-Path $dir $meta.FileName
        $envName = $meta.EnvName
        $value = ""

        if (Test-Path $file) {
            $value = (Get-Content -Path $file -Raw -Encoding ASCII).Trim()
        }
        if ([string]::IsNullOrWhiteSpace($value)) {
            $value = New-BackendTokenValue
            Set-Content -Path $file -Value $value -Encoding ASCII -NoNewline
        }
        Set-Item -Path "Env:$envName" -Value $value
    }
}

function Show-BackendTokenStatus {
    $dir = Get-BackendSecretsDir
    Write-Host "Backend gateway credentials ready (values not printed):" -ForegroundColor DarkGray
    foreach ($svc in $Script:BackendTokenMap.Keys) {
        $meta = $Script:BackendTokenMap[$svc]
        $file = Join-Path $dir $meta.FileName
        $present = Test-Path $file
        Write-Host "  $svc  env=$($meta.EnvName)  file=$(if ($present) { 'yes' } else { 'missing' })" -ForegroundColor DarkGray
    }
}