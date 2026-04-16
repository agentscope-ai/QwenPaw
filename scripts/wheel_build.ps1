# Build a full wheel package including the latest console frontend.
# Run from repo root: pwsh -File scripts/wheel_build.ps1

$ErrorActionPreference = "Stop"
$RepoRoot = (Get-Item $PSScriptRoot).Parent.FullName
Set-Location $RepoRoot

$ConsoleDir = Join-Path $RepoRoot "console"
$ConsoleDest = Join-Path $RepoRoot "src\qwenpaw\console"

Write-Host "[wheel_build] Building console frontend..."

# Ensure pnpm is available
if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
    if (Get-Command npm -ErrorAction SilentlyContinue) {
        Write-Host "pnpm not found, installing via npm..."
        npm install -g pnpm
    } else {
        throw "pnpm not found and npm is also not available. Install Node.js first."
    }
}

Push-Location $ConsoleDir
try {
  pnpm install
  if ($LASTEXITCODE -ne 0) { throw "pnpm install failed with exit code $LASTEXITCODE" }
  pnpm run build
  if ($LASTEXITCODE -ne 0) { throw "pnpm run build failed with exit code $LASTEXITCODE" }
} finally {
  Pop-Location
}

Write-Host "[wheel_build] Copying console/dist/* -> src/qwenpaw/console/..."
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
