# Write QwenPaw MCP JSON configs for the unified-gateway demo.
# - gateway-client.json       : valid employee JWT (value not printed)
# - gateway-no-token.json     : gateway URL, no Authorization
# - gateway-forged-client.json: gateway URL + deliberately bad JWT

. "$PSScriptRoot\_common.ps1"

$ErrorActionPreference = "Stop"
Set-DeployLocation

$tokenFile = Join-DemoPath "jwt\employeeQwenpaw.key"
if (-not (Test-Path $tokenFile)) {
    Write-Host "ERROR: missing $tokenFile" -ForegroundColor Red
    exit 1
}
$token = (Get-Content -Path $tokenFile -Raw -Encoding UTF8).Trim()

$outDir = Join-DemoPath "qwenpaw"
if (-not (Test-Path $outDir)) {
    New-Item -ItemType Directory -Force -Path $outDir | Out-Null
}

function Write-JsonFile {
    param(
        [string]$Path,
        [hashtable]$Payload
    )
    ($Payload | ConvertTo-Json -Depth 6) | Set-Content -Path $Path -Encoding UTF8
}

# 1) Valid token client
$validPath = Join-Path $outDir "gateway-client.json"
Write-JsonFile -Path $validPath -Payload ([ordered]@{
    key         = "agentgateway-unified"
    name        = "AgentGateway Unified"
    description = "Unified gateway entry with employeeQwenpaw JWT"
    enabled     = $true
    transport   = "streamable_http"
    url         = "http://localhost:3000/mcp"
    headers     = [ordered]@{
        Authorization = "Bearer $token"
    }
})

# 2) No-token client (static shape; overwrite to keep in sync)
$noTokenPath = Join-Path $outDir "gateway-no-token.json"
Write-JsonFile -Path $noTokenPath -Payload ([ordered]@{
    key         = "agentgateway-no-token"
    name        = "AgentGateway (no Token)"
    description = "Unified gateway entry without Authorization"
    enabled     = $true
    transport   = "streamable_http"
    url         = "http://localhost:3000/mcp"
})

# 3) Forged token client (wrong signature / no kid matching JWKS)
$forged = @"
eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJhZ2VudGdhdGV3YXkuZGV2IiwiYXVkIjoidGVzdC5hZ2VudGdhdGV3YXkuZGV2IiwiZXhwIjoxODkzNDU2MDAwLCJzdWIiOiJmb3JnZWRBZ2VudCJ9.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB
"@.Trim()

$forgedPath = Join-Path $outDir "gateway-forged-client.json"
Write-JsonFile -Path $forgedPath -Payload ([ordered]@{
    key         = "agentgateway-forged"
    name        = "AgentGateway (forged Token)"
    description = "Unified gateway entry with a forged JWT (must be rejected)"
    enabled     = $true
    transport   = "streamable_http"
    url         = "http://localhost:3000/mcp"
    headers     = [ordered]@{
        Authorization = "Bearer $forged"
    }
})

Write-Host "Wrote QwenPaw MCP configs (token values not printed):" -ForegroundColor Green
Write-Host "  $validPath"
Write-Host "  $noTokenPath"
Write-Host "  $forgedPath"
Write-Host "Import in QwenPaw: Agents -> MCP -> Create / JSON"
