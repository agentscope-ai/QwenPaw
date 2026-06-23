# Install Tauri via NSIS, launch the shell, and wait for the backend.
# Outputs BASE_URL to $env:GITHUB_ENV for subsequent steps.
$ErrorActionPreference = "Stop"

# 1. Run NSIS silent install (matches real user installer).
#    /S = silent, run the installer to completion before continuing.
$installer = Get-ChildItem dist/QwenPaw-Tauri-*-Windows-setup.exe |
  Select-Object -First 1
if (-not $installer) { throw "NSIS installer not found in dist/" }
Write-Host "Installing $($installer.Name) silently..."
$proc = Start-Process -FilePath $installer.FullName -ArgumentList "/S" `
  -Wait -PassThru -NoNewWindow
Write-Host "Installer exited with code $($proc.ExitCode)"
if ($proc.ExitCode -ne 0) {
  throw "NSIS installer failed (exit $($proc.ExitCode))"
}
# Tauri NSIS spawns elevated child + finishes immediately; allow time for
# files to settle.
Start-Sleep -Seconds 5

# 2. Locate the installed Tauri exe.
#    Tauri NSIS may install to versioned subdirs, so search recursively
#    inside each candidate root.
$candidateRoots = @(
  (Join-Path $env:LOCALAPPDATA "QwenPaw Desktop"),
  (Join-Path $env:LOCALAPPDATA "Programs\QwenPaw Desktop"),
  (Join-Path $env:ProgramFiles "QwenPaw Desktop"),
  (Join-Path ${env:ProgramFiles(x86)} "QwenPaw Desktop")
)
$tauriExe = $null
foreach ($root in $candidateRoots) {
  if (Test-Path $root) {
    $found = Get-ChildItem -Path $root -Filter "qwenpaw-desktop.exe" `
      -Recurse -Depth 3 -ErrorAction SilentlyContinue |
      Select-Object -First 1
    if ($found) { $tauriExe = $found.FullName; break }
  }
}
if (-not $tauriExe) {
  foreach ($hive in @("HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                      "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
                      "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")) {
    $reg = Get-ChildItem $hive -ErrorAction SilentlyContinue |
      Where-Object { (Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue).DisplayName -match "QwenPaw" } |
      Select-Object -First 1
    if ($reg) {
      $loc = (Get-ItemProperty $reg.PSPath).InstallLocation
      if ($loc -and (Test-Path $loc)) {
        $found = Get-ChildItem -Path $loc -Filter "qwenpaw-desktop.exe" `
          -Recurse -Depth 3 -ErrorAction SilentlyContinue |
          Select-Object -First 1
        if ($found) { $tauriExe = $found.FullName; break }
      }
    }
  }
}
if (-not $tauriExe) {
  Write-Host "=== DEBUG: install location not found ==="
  foreach ($root in $candidateRoots) {
    Write-Host "Candidate: $root  exists=$([bool](Test-Path $root))"
    if (Test-Path $root) {
      Write-Host "  Contents (depth 2):"
      Get-ChildItem -Path $root -Recurse -Depth 2 -ErrorAction SilentlyContinue |
        Select-Object -First 30 | ForEach-Object { Write-Host "    $($_.FullName)" }
    }
  }
  throw "Tauri exe not found after NSIS install"
}
Write-Host "Installed at: $tauriExe"

# 3. Pre-delete BOOTSTRAP.md so the agent answers in plain QA mode.
$wsDir = Join-Path $env:USERPROFILE ".qwenpaw\workspaces\default"
New-Item -ItemType Directory -Force -Path $wsDir | Out-Null
$bootstrapMd = Join-Path $wsDir "BOOTSTRAP.md"
if (Test-Path $bootstrapMd) { Remove-Item -Force $bootstrapMd }

# 4. Launch the full Tauri shell (matches real user double-click).
Start-Process -FilePath $tauriExe

# 5. Wait for the sidecar to write the port file and respond.
#    The sidecar writes desktop_port at WORKING_DIR root (~/.qwenpaw),
#    not inside the workspace dir.
$portFile = Join-Path $env:USERPROFILE ".qwenpaw\desktop_port"
$port = $null
$deadline = (Get-Date).AddSeconds(120)
while ((Get-Date) -lt $deadline) {
  if (Test-Path $portFile) {
    $port = (Get-Content $portFile -ErrorAction SilentlyContinue).Trim()
    if ($port) {
      try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/api/version" `
          -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
        if ($r.StatusCode -eq 200) {
          Write-Host "Tauri app ready on port $port"
          break
        }
      } catch {}
    }
  }
  Start-Sleep -Seconds 2
}
if (-not $port) {
  Write-Host "::error::Tauri app did not start within 120s"
  exit 1
}

$baseUrl = "http://127.0.0.1:$port"
$env:BASE_URL = $baseUrl
"BASE_URL=$baseUrl" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
Write-Host $baseUrl
