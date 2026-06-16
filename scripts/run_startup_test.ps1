# Startup timing test with auto-terminate
# Run from QwenPaw root directory

$ErrorActionPreference = "Stop"
$RepoRoot = (Get-Item $PSScriptRoot).Parent.FullName
Set-Location $RepoRoot

$env:QWENPAW_DESKTOP_APP = "1"
$env:QWENPAW_LOG_LEVEL = "info"

$logFile = Join-Path $RepoRoot "startup_test_output.log"
$errFile = Join-Path $RepoRoot "startup_test_err.log"
if (Test-Path $logFile) { Remove-Item $logFile -Force }
if (Test-Path $errFile) { Remove-Item $errFile -Force }

Write-Host "=== Startup Timing Test ==="
Write-Host "Start: $(Get-Date -Format 'HH:mm:ss.fff')"
Write-Host ""

$proc = Start-Process -FilePath "python" `
    -ArgumentList "-u", "-m", "qwenpaw", "desktop", "--log-level", "info" `
    -PassThru -NoNewWindow `
    -RedirectStandardOutput $logFile `
    -RedirectStandardError $errFile

$startTime = Get-Date
$foundLoading = $false
$foundBackendReady = $false
$foundNav = $false
$timeout = 90

while (-not $proc.HasExited -and ((Get-Date) - $startTime).TotalSeconds -lt $timeout) {
    Start-Sleep -Milliseconds 500

    if (Test-Path $logFile) {
        $content = Get-Content $logFile -Raw -ErrorAction SilentlyContinue

        if (-not $foundLoading -and $content -match "Creating webview window with loading page") {
            $foundLoading = $true
            $t = [math]::Round(((Get-Date) - $startTime).TotalSeconds, 1)
            Write-Host "[{0}s] Loading page window created" -f $t
        }

        if (-not $foundBackendReady -and $content -match "HTTP backend is ready") {
            $foundBackendReady = $true
            $t = [math]::Round(((Get-Date) - $startTime).TotalSeconds, 1)
            Write-Host "[{0}s] Backend HTTP ready" -f $t
        }

        if (-not $foundNav -and $content -match "Backend ready, navigating to app URL") {
            $foundNav = $true
            $t = [math]::Round(((Get-Date) - $startTime).TotalSeconds, 1)
            Write-Host "[{0}s] Navigating to app URL" -f $t
        }

        # Stop once we see navigation or server ready
        if ($foundNav -or ($content -match "webview.start\(\) returned")) {
            break
        }
    }
}

$elapsed = [math]::Round(((Get-Date) - $startTime).TotalSeconds, 1)
Write-Host ""
Write-Host "=== Results (elapsed: ${elapsed}s) ==="
Write-Host "  Loading page:  $(if($foundLoading){'OK'}else{'NOT DETECTED'})"
Write-Host "  Backend ready: $(if($foundBackendReady){'OK'}else{'NOT DETECTED'})"
Write-Host "  Navigation:    $(if($foundNav){'OK'}else{'NOT DETECTED'})"
Write-Host ""

# Cleanup
if (-not $proc.HasExited) {
    Write-Host "Terminating process..."
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}
Remove-Item $logFile -ErrorAction SilentlyContinue
Remove-Item (Join-Path $PSScriptRoot ".." "startup_test_err.log") -ErrorAction SilentlyContinue
Write-Host "Done."
