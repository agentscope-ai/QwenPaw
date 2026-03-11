# Build a full wheel package including the latest console frontend.
# Run from repo root: pwsh -File scripts/wheel_build.ps1

$ErrorActionPreference = "Stop"
$RepoRoot = (Get-Item $PSScriptRoot).Parent.FullName
Set-Location $RepoRoot

$ConsoleDir = Join-Path $RepoRoot "console"
$ConsoleDest = Join-Path $RepoRoot "src\copaw\console"

Write-Host "[wheel_build] Building console frontend..."
Push-Location $ConsoleDir
try {
  npm ci
  if ($LASTEXITCODE -ne 0) { throw "npm ci failed with exit code $LASTEXITCODE" }
  npm run build
  if ($LASTEXITCODE -ne 0) { throw "npm run build failed with exit code $LASTEXITCODE" }
} finally {
  Pop-Location
}

Write-Host "[wheel_build] Copying console/dist/* -> src/copaw/console/..."
if (Test-Path $ConsoleDest) {
  Remove-Item -Path (Join-Path $ConsoleDest "*") -Recurse -Force -ErrorAction SilentlyContinue
} else {
  New-Item -ItemType Directory -Force -Path $ConsoleDest | Out-Null
}
$ConsoleDist = Join-Path $ConsoleDir "dist"
Copy-Item -Path (Join-Path $ConsoleDist "*") -Destination $ConsoleDest -Recurse -Force

Write-Host "[wheel_build] Building wheel + sdist..."
python -m pip install --quiet build
$DistDir = Join-Path $RepoRoot "dist"
if (Test-Path $DistDir) {
  Remove-Item -Path (Join-Path $DistDir "*") -Force -ErrorAction SilentlyContinue
}
python -m build --outdir dist .
if ($LASTEXITCODE -ne 0) { throw "python -m build failed with exit code $LASTEXITCODE" }

Write-Host "[wheel_build] Done. Wheel(s) in: $RepoRoot\dist\"
