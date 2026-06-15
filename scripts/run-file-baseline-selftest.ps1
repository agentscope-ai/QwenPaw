# Run File baseline self-test net (wiring + backend + frontend).
param(
    [string[]]$Layer,
    [switch]$List
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
$Runner = Join-Path $ScriptDir "run-file-baseline-selftest.py"

$Args = @()
if ($List) { $Args += "--list" }
foreach ($Name in $Layer) {
    $Args += @("--layer", $Name)
}

Push-Location $RepoRoot
try {
    python $Runner @Args
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
