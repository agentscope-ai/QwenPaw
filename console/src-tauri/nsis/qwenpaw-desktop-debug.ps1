$ErrorActionPreference = "Continue"
$utf8 = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8

$desktopExe = Join-Path $PSScriptRoot "qwenpaw-desktop.exe"
$stdoutLog = Join-Path $env:TEMP "qwenpaw-desktop-debug.stdout.log"
$stderrLog = Join-Path $env:TEMP "qwenpaw-desktop-debug.stderr.log"
Remove-Item -LiteralPath $stdoutLog, $stderrLog -ErrorAction SilentlyContinue

function Show-DesktopOutput {
  foreach ($item in @(@("stdout", $stdoutLog), @("stderr", $stderrLog))) {
    if (Test-Path -LiteralPath $item[1]) {
      $text = Get-Content -Encoding UTF8 -LiteralPath $item[1] -Raw
      if ($text) {
        Write-Host ""
        Write-Host "==> desktop $($item[0]) <=="
        Write-Host $text
      }
    }
  }
}

function Open-Log($label, $paths) {
  $path = $paths | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
  if (-not $path) {
    return $null
  }
  try {
    $stream = [System.IO.File]::Open($path, "Open", "Read", "ReadWrite")
    $reader = [System.IO.StreamReader]::new($stream, $utf8, $true)
    while ($reader.ReadLine() -ne $null) {}
    Write-Host ""
    Write-Host "==> ${label}: $path <=="
    [pscustomobject]@{ Label = $label; Reader = $reader; Stream = $stream }
  } catch {
    Write-Host "Failed to open ${label} log: $path"
    Write-Host $_.Exception.Message
    $null
  }
}

$desktop = Get-Process -Name "qwenpaw-desktop" -ErrorAction SilentlyContinue |
  Where-Object { $_.Path -eq $desktopExe } |
  Select-Object -First 1
if ($desktop) {
  Write-Host "Existing QwenPaw Desktop process detected; quit it from the tray before reproducing startup issues."
  $desktop = $null
} else {
  $desktop = Start-Process -FilePath $desktopExe `
    -WorkingDirectory $PSScriptRoot `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -PassThru
}

$specs = @(
  [pscustomobject]@{ Label = "backend"; Paths = $env:QWENPAW_BACKEND_LOGS -split ";" },
  [pscustomobject]@{ Label = "shell"; Paths = $env:QWENPAW_SHELL_LOGS -split ";" }
)
$states = @()

try {
  Write-Host "Watching logs. Press Ctrl+C to stop."
  while ($true) {
    foreach ($spec in $specs) {
      if ($states.Label -notcontains $spec.Label) {
        $state = Open-Log $spec.Label $spec.Paths
        if ($state) {
          $states += $state
        }
      }
    }
    foreach ($state in $states) {
      while (($line = $state.Reader.ReadLine()) -ne $null) {
        Write-Host "[$($state.Label)] $line"
      }
    }
    if ($desktop) {
      $desktop.Refresh()
      if ($desktop.HasExited) {
        Write-Host "QwenPaw Desktop exited with code $($desktop.ExitCode)."
        Show-DesktopOutput
        Read-Host "Press Enter to exit"
        break
      }
    }
    Start-Sleep -Milliseconds 500
  }
} finally {
  foreach ($state in $states) {
    $state.Reader.Dispose()
    $state.Stream.Dispose()
  }
}
