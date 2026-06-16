# Quick startup timing test for desktop optimization.
# Measures: loading page appearance time + backend HTTP ready time.
# Usage: .\scripts\test_startup_timing.ps1

$ErrorActionPreference = "Stop"
$RepoRoot = (Get-Item $PSScriptRoot).Parent.FullName
Set-Location $RepoRoot

$env:QWENPAW_DESKTOP_APP = "1"
$env:QWENPAW_LOG_LEVEL = "info"

$startTime = Get-Date
Write-Host "=== Startup Timing Test ==="
Write-Host "Start time: $($startTime.ToString('HH:mm:ss.fff'))"
Write-Host ""

$pythonExe = "python"
$logFile = Join-Path $RepoRoot "startup_test.log"
$errFile = Join-Path $RepoRoot "startup_test_err.log"

# Start desktop in background, capture output
$proc = Start-Process -FilePath $pythonExe `
    -ArgumentList "-u", "-m", "qwenpaw", "desktop", "--log-level", "info" `
    -PassThru `
    -RedirectStandardOutput $logFile `
    -RedirectStandardError $errFile `
    -NoNewWindow

Write-Host "Process started (PID: $($proc.Id)), waiting for signals..."
Write-Host ""

$loadingPageTime = $null
$backendReadyTime = $null
$timeout = 120
$elapsed = 0

while ($elapsed -lt $timeout) {
    Start-Sleep -Milliseconds 500
    $elapsed = [math]::Round((Get-Date - $startTime).TotalSeconds, 1)

    if (Test-Path $logFile) {
        $content = Get-Content $logFile -ErrorAction SilentlyContinue
        if (Test-Path $errFile) {
            $errContent = Get-Content $errFile -ErrorAction SilentlyContinue
            $content = $content + $errContent
        }

        # Check for loading page creation signal
        if (-not $loadingPageTime -and ($content | Select-String -Quiet "Creating webview window with loading page")) {
            $loadingPageTime = [math]::Round((Get-Date - $startTime).TotalSeconds, 1)
            Write-Host "[{0}s] Loading page window created" -f $loadingPageTime
        }

        # Check for backend HTTP ready signal
        if (-not $backendReadyTime -and ($content | Select-String -Quiet "HTTP backend is ready")) {
            $backendReadyTime = [math]::Round((Get-Date - $startTime).TotalSeconds, 1)
            Write-Host "[{0}s] Backend HTTP ready" -f $backendReadyTime
        }

        # Check for navigation signal
        if ($content | Select-String -Quiet "Backend ready, navigating to app URL") {
            $navTime = [math]::Round((Get-Date - $startTime).TotalSeconds, 1)
            Write-Host "[{0}s] Navigating to app URL" -f $navTime
            break
        }
    }

    if ($proc.HasExited) {
        Write-Host "Process exited with code: $($proc.ExitCode)"
        break
    }
}

Write-Host ""
Write-Host "=== Results ==="
if ($loadingPageTime) {
    Write-Host "  Loading page appeared:  {$loadingPageTime}s"
} else {
    Write-Host "  Loading page appeared:  NOT DETECTED (timeout)"
}
if ($backendReadyTime) {
    Write-Host "  Backend HTTP ready:     {$backendReadyTime}s"
} else {
    Write-Host "  Backend HTTP ready:     NOT DETECTED (timeout)"
}
$totalTime = [math]::Round((Get-Date - $startTime).TotalSeconds, 1)
Write-Host "  Total elapsed:            {$totalTime}s"
Write-Host ""

# Cleanup
Write-Host "Terminating test process..."
if (-not $proc.HasExited) {
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
}
Remove-Item $logFile -ErrorAction SilentlyContinue
Write-Host "Done."
