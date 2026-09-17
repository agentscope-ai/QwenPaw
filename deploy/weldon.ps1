[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("init", "up", "down", "status", "logs", "backup", "restore", "help")]
    [string]$Command = "help",

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArgs
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$EnvFile = if ($env:WELDON_ENV_FILE) { $env:WELDON_ENV_FILE } else { Join-Path $ScriptDir ".env" }
$ComposeFile = Join-Path $ScriptDir "compose.production.yml"

function Show-Usage {
    @(
        "WeldonAgent deployment commands:"
        "  init     validate, build, initialize, and start"
        "  up       start an initialized instance"
        "  down     stop containers without deleting data"
        "  status   show container and application health"
        "  logs     follow application logs"
        "  backup   create a consistent backup"
        "  restore  restore into an empty data root"
    ) | Write-Output
}

function Invoke-Compose {
    param([string[]]$Arguments)
    & docker compose `
        --project-name weldonagent `
        --env-file $EnvFile `
        --file $ComposeFile `
        @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose failed with exit code $LASTEXITCODE"
    }
}

function Read-EnvValue {
    param([string]$Name)
    $line = Get-Content -LiteralPath $EnvFile -Encoding UTF8 |
        Where-Object { $_ -match "^\s*$([regex]::Escape($Name))\s*=" } |
        Select-Object -Last 1
    if (-not $line) { return "" }
    $value = ($line -split "=", 2)[1].Trim()
    return $value.Trim('"').Trim("'")
}

function Test-Preflight {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker was not found"
    }
    & docker compose version *> $null
    if ($LASTEXITCODE -ne 0) { throw "Docker Compose v2 is required" }
    if (-not (Test-Path -LiteralPath $EnvFile -PathType Leaf)) {
        throw "Missing $EnvFile; copy .env.production.example and configure it"
    }
    $dataRoot = Read-EnvValue "WELDON_DATA_ROOT"
    if ([string]::IsNullOrWhiteSpace($dataRoot)) { throw "WELDON_DATA_ROOT is required" }
    $password = Read-EnvValue "WELDON_DB_PASSWORD"
    if ($password -eq "REPLACE_WITH_RANDOM_PASSWORD" -or $password.Length -lt 16) {
        throw "WELDON_DB_PASSWORD must contain at least 16 characters"
    }
    @("working", "secrets", "backups", "logs", "run", "postgres") |
        ForEach-Object {
            New-Item -ItemType Directory -Force -Path (Join-Path $dataRoot $_) | Out-Null
        }
    Invoke-Compose @("config", "--quiet")
}

switch ($Command) {
    "init" {
        Test-Preflight
        Invoke-Compose @("build", "agent-init", "agent-app")
        Invoke-Compose @("up", "-d", "agent-pg")
        Invoke-Compose @("--profile", "init", "run", "--rm", "agent-init")
        Invoke-Compose @("up", "-d", "agent-app")
        Invoke-Compose @("ps")
    }
    "up" {
        Test-Preflight
        Invoke-Compose @("up", "-d", "agent-pg", "agent-app")
    }
    "down" { Invoke-Compose @("down") }
    "status" {
        Invoke-Compose @("ps")
        Invoke-Compose @(
            "exec", "-T", "agent-app",
            "python", "/app/deploy/runtime_env.py", "exec", "--",
            "python", "-m", "qwenpaw", "service", "--config",
            "/app/deploy/service.production.json", "status"
        )
    }
    "logs" { Invoke-Compose @("logs", "--tail=200", "-f", "agent-app") }
    "backup" {
        Test-Preflight
        Invoke-Compose @("up", "-d", "agent-pg")
        try {
            Invoke-Compose @("stop", "agent-app")
        } catch {}
        try {
            Invoke-Compose (@("--profile", "maintenance", "run", "--rm", "agent-maintenance", "backup") + $RemainingArgs)
        } finally {
            Invoke-Compose @("up", "-d", "agent-app")
        }
    }
    "restore" {
        Test-Preflight
        if (-not $RemainingArgs -or $RemainingArgs.Count -eq 0) {
            throw "restore requires a backup directory under /data/backups"
        }
        Invoke-Compose @("up", "-d", "agent-pg")
        try {
            Invoke-Compose @("stop", "agent-app")
        } catch {}
        Invoke-Compose (@("--profile", "maintenance", "run", "--rm", "agent-maintenance", "restore") + $RemainingArgs)
        Invoke-Compose @("--profile", "init", "run", "--rm", "agent-init")
        Invoke-Compose @("up", "-d", "agent-app")
    }
    default { Show-Usage }
}
