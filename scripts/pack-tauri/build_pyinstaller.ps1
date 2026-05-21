# Build QwenPaw backend with PyInstaller for Tauri sidecar (Windows)
# Creates an onedir backend bundle with embedded Python runtime
#
# Usage:
#   powershell ./scripts/pack-tauri/build_pyinstaller.ps1
#
# Prerequisites:
#   - Python 3.10+

param()

$ErrorActionPreference = "Stop"
$REPO_ROOT = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $REPO_ROOT

$python = Join-Path $REPO_ROOT ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = (Get-Command python -ErrorAction SilentlyContinue).Source
}
if (-not $python) {
    throw "Python not found in .venv or PATH"
}

& $python "scripts\pack-tauri\build_pyinstaller_backend.py"
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller backend build failed"
}
