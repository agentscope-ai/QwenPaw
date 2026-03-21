# Start RyPaw Desktop in development mode (Windows)
# This starts both the Python backend and Electron frontend with hot reload

$ErrorActionPreference = "Stop"
$RepoRoot = (Get-Item $PSScriptRoot).Parent.FullName
Set-Location $RepoRoot

Write-Host "== Starting RyPaw Desktop (Development Mode) =="
Write-Host "[dev] REPO_ROOT=$RepoRoot"

# Check if Node.js is installed
try {
  $nodeVersion = node --version
  Write-Host "[dev] Node.js version: $nodeVersion"
} catch {
  Write-Host "[dev] ERROR: Node.js not found. Please install Node.js first."
  exit 1
}

# Install Electron dependencies if not already installed
$ElectronDir = Join-Path $RepoRoot "electron"
if (-not (Test-Path (Join-Path $ElectronDir "node_modules"))) {
  Write-Host "[dev] Installing Electron dependencies..."
  Set-Location $ElectronDir
  npm install
  Set-Location $RepoRoot
}

# Set development environment
$env:NODE_ENV = "development"
$env:RYPAW_LOG_LEVEL = if ($env:RYPAW_LOG_LEVEL) { $env:RYPAW_LOG_LEVEL } else { "debug" }

Write-Host "[dev] Starting Electron in development mode..."
Write-Host "[dev] - Python backend: system Python"
Write-Host "[dev] - Frontend: http://localhost:18765"
Write-Host "[dev] - Press Ctrl+C to stop"

Set-Location $ElectronDir
npm run dev
