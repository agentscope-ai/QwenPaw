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
#    Priority: registry InstallLocation (canonical) → known candidate dirs.
$tauriExe = $null

# Try registry first — Tauri NSIS always writes InstallLocation.
foreach ($hive in @("HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                    "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall")) {
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

# Fallback: search known install candidate directories.
if (-not $tauriExe) {
  $candidateRoots = @(
    (Join-Path $env:LOCALAPPDATA "QwenPaw Desktop"),
    (Join-Path $env:LOCALAPPDATA "Programs\QwenPaw Desktop"),
    (Join-Path $env:ProgramFiles "QwenPaw Desktop"),
    (Join-Path ${env:ProgramFiles(x86)} "QwenPaw Desktop")
  )
  foreach ($root in $candidateRoots) {
    if (Test-Path $root) {
      $found = Get-ChildItem -Path $root -Filter "qwenpaw-desktop.exe" `
        -Recurse -Depth 3 -ErrorAction SilentlyContinue |
        Select-Object -First 1
      if ($found) { $tauriExe = $found.FullName; break }
    }
  }
}

if (-not $tauriExe) {
  Write-Host "=== DEBUG: install location not found ==="
  Write-Host "Registry entries matching QwenPaw:"
  foreach ($hive in @("HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                      "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")) {
    Get-ChildItem $hive -ErrorAction SilentlyContinue |
      Where-Object { (Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue).DisplayName -match "QwenPaw" } |
      ForEach-Object { Write-Host "  $((Get-ItemProperty $_.PSPath).InstallLocation)" }
  }
  throw "Tauri exe not found after NSIS install"
}
Write-Host "Installed at: $tauriExe"

# 2b. Verify WebView2 bootstrapper is bundled in the install.
$installRoot = Split-Path $tauriExe -Parent
$wv2Files = Get-ChildItem -Path $installRoot -Filter "*WebView2*" `
  -Recurse -Depth 3 -ErrorAction SilentlyContinue
if ($wv2Files) {
  Write-Host "WebView2 bootstrapper present: $($wv2Files[0].Name)"
} else {
  Write-Host "::warning::WebView2 bootstrapper not found in install dir"
}

# 3. Launch the full Tauri shell with CDP debugging enabled.
#    This makes WebView2 expose a Chrome DevTools Protocol port so
#    Playwright can connect_over_cdp() to the real embedded webview.
$cdpPort = 9222
$env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = "--remote-debugging-port=$cdpPort"
$elevated = [Security.Principal.WindowsPrincipal]::new(
  [Security.Principal.WindowsIdentity]::GetCurrent()
).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Write-Host "Desktop verification host elevated: $elevated"
$policy = $null
$previousArgs = $null
$previousKind = $null
$policyApp = [IO.Path]::GetFileName($tauriExe)
try {
  # Elevated WebView2 ignores environment overrides. Use a per-app,
  # machine-scoped policy only on the disposable CI runner, then restore it.
  if ($elevated -and $env:GITHUB_ACTIONS -eq "true") {
    $policy = [Microsoft.Win32.Registry]::LocalMachine.CreateSubKey(
      "SOFTWARE\Policies\Microsoft\Edge\WebView2\AdditionalBrowserArguments"
    )
    $previousArgs = $policy.GetValue($policyApp)
    if ($null -ne $previousArgs) { $previousKind = $policy.GetValueKind($policyApp) }
    $policy.SetValue($policyApp, "--remote-debugging-port=$cdpPort")
  }
  $desktop = Start-Process -FilePath $tauriExe -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $env:RUNNER_TEMP "qwenpaw-desktop-stdout.log") `
    -RedirectStandardError (Join-Path $env:RUNNER_TEMP "qwenpaw-desktop-stderr.log") `
    -PassThru
  Write-Host "Desktop verification PID: $($desktop.Id)"

  # 4. Wait for the sidecar to write the port file and respond.
  #    The sidecar writes desktop_port at WORKING_DIR root (~/.qwenpaw),
  #    not inside the workspace dir.
  $portFile = Join-Path $env:USERPROFILE ".qwenpaw\desktop_port"
  $port = $null
  $backendReady = $false
  $deadline = (Get-Date).AddSeconds(120)
  while ((Get-Date) -lt $deadline) {
    if ($desktop.HasExited) {
      throw "Desktop exited before backend readiness (exit $($desktop.ExitCode))"
    }
    if (Test-Path $portFile) {
      $port = (Get-Content $portFile -ErrorAction SilentlyContinue).Trim()
      if ($port) {
        try {
          $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/console" `
            -NoProxy -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
          if ($r.StatusCode -eq 200) {
            Write-Host "Tauri app ready on port $port"
            $backendReady = $true
            break
          }
        } catch {}
      }
    }
    Start-Sleep -Seconds 2
  }
  if (-not $backendReady) {
    throw "Tauri app did not start within 120s"
  }

  # 5. Auto-init creates BOOTSTRAP.md during startup. Remove it afterwards so
  #    the verifier can drive the agent in normal QA mode.
  $bootstrapMd = Join-Path $env:USERPROFILE ".qwenpaw\workspaces\default\BOOTSTRAP.md"
  if (Test-Path $bootstrapMd) { Remove-Item -Force $bootstrapMd }

  # 6. Wait for CDP endpoint to become available.
  $cdpUrl = "http://127.0.0.1:$cdpPort"
  $cdpReady = $false
  for ($i = 1; $i -le 30; $i++) {
    try {
      $r = Invoke-WebRequest -Uri "$cdpUrl/json/version" `
        -NoProxy -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
      if ($r.StatusCode -eq 200) {
        Write-Host "CDP ready at $cdpUrl"
        $cdpReady = $true
        break
      }
    } catch { Start-Sleep -Seconds 2 }
  }
  if (-not $cdpReady) {
    throw "CDP not available; Windows verification requires the native WebView"
  }
} finally {
  if ($null -ne $policy) {
    if ($null -eq $previousArgs) {
      $policy.DeleteValue($policyApp, $false)
    } else {
      $policy.SetValue($policyApp, $previousArgs, $previousKind)
    }
    $policy.Close()
  }
}

$baseUrl = "http://127.0.0.1:$port"
$env:BASE_URL = $baseUrl
$env:CDP_URL = $cdpUrl
"BASE_URL=$baseUrl" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
"CDP_URL=$cdpUrl" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
Write-Host "BASE_URL=$baseUrl"
Write-Host "CDP_URL=$cdpUrl"
