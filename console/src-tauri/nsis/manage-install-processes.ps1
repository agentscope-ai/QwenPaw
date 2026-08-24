param(
    [Parameter(Mandatory = $true)]
    [string]$InstallDir,
    [ValidateSet("Prepare", "Restore")]
    [string]$Action = "Prepare",
    [string]$StateFile = "",
    [switch]$TerminateUnknown
)

# Prepare a recognized QwenPaw installation for NSIS replacement. The script
# intentionally uses only cmdlets, operators, and core type methods so it also
# works under WDAC/AppLocker ConstrainedLanguage mode.

$ErrorActionPreference = "Stop"
$gateMarker = "QWENPAW_INSTALL_MAINTENANCE"
$launcher = Join-Path $env:USERPROFILE ".qwenpaw\bin\qwenpaw-nm-host.bat"
$launcherBackup = "$launcher.qwenpaw-maintenance"

function Get-NormalizedPath {
    param([string]$Path)

    if (-not $Path) {
        return ""
    }
    if ($Path.StartsWith("\\?\UNC\")) {
        return "\\" + $Path.Substring(8)
    }
    if ($Path.StartsWith("\\?\")) {
        return $Path.Substring(4)
    }
    return $Path
}

function Test-PathBelowRoot {
    param(
        [string]$Path,
        [string]$Root
    )

    if (-not $Path -or $Path.Length -le $Root.Length) {
        return $false
    }
    return (
        $Path.Substring(0, $Root.Length) -ieq $Root -and
        $Path.Substring($Root.Length, 1) -eq "\"
    )
}

function Test-IsMaintenanceStub {
    if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
        return $false
    }
    return (Get-Content -LiteralPath $launcher -Raw).Contains($gateMarker)
}

function Test-LauncherTargetsRoot {
    param([string]$Root)

    $needles = @(
        ($Root + "\").ToLowerInvariant(),
        ($Root.Replace("%", "%%") + "\").ToLowerInvariant()
    ) | Sort-Object -Unique
    foreach ($path in @($launcher, $launcherBackup)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            continue
        }
        $content = Get-Content -LiteralPath $path -Raw
        $lowerContent = $content.ToLowerInvariant()
        foreach ($needle in $needles) {
            if ($lowerContent.Contains($needle)) {
                return $true
            }
        }
    }
    return $false
}

function Restore-NativeHostLauncher {
    param([string]$Root)

    if (-not $Root -or -not (Test-LauncherTargetsRoot -Root $Root)) {
        return
    }
    if (-not (Test-Path -LiteralPath $launcherBackup -PathType Leaf)) {
        return
    }
    if ((Test-Path -LiteralPath $launcher -PathType Leaf) -and
        -not (Test-IsMaintenanceStub)) {
        Remove-Item -LiteralPath $launcherBackup -Force
        return
    }
    if (Test-Path -LiteralPath $launcher -PathType Leaf) {
        Remove-Item -LiteralPath $launcher -Force
    }
    Move-Item -LiteralPath $launcherBackup -Destination $launcher -Force
}

function Enable-NativeHostGate {
    param([string]$Root)

    if (-not (Test-LauncherTargetsRoot -Root $Root)) {
        return
    }
    if (Test-Path -LiteralPath $launcherBackup -PathType Leaf) {
        if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
            return
        }
        if (Test-IsMaintenanceStub) {
            return
        }
        Remove-Item -LiteralPath $launcherBackup -Force
    }
    if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
        return
    }

    Move-Item -LiteralPath $launcher -Destination $launcherBackup -Force
    try {
        Set-Content -LiteralPath $launcher -Encoding Ascii -Value @(
            "@echo off",
            "rem $gateMarker",
            "exit /b 0"
        )
    } catch {
        Move-Item -LiteralPath $launcherBackup -Destination $launcher -Force
        throw
    }
}

function Get-InstallRoot {
    if (-not (Test-Path -LiteralPath $InstallDir -PathType Container)) {
        return $null
    }
    $item = Get-Item -LiteralPath $InstallDir
    if ("$($item.Attributes)" -match "ReparsePoint") {
        throw "The QwenPaw installation directory cannot be a reparse point."
    }
    return (Get-NormalizedPath -Path $item.FullName).TrimEnd("\")
}

function Get-InstallState {
    param([string]$Root)

    if (-not $Root) {
        return "Fresh"
    }
    $firstEntry = Get-ChildItem -LiteralPath $Root -Force |
        Select-Object -First 1
    if ($null -eq $firstEntry) {
        return "Fresh"
    }

    $evidence = 0
    foreach ($path in @(
        (Join-Path $Root "qwenpaw-desktop.exe"),
        (Join-Path $Root "binaries\qwenpaw-backend\qwenpaw-backend.exe"),
        (Join-Path $Root "binaries\python-runtime\python\python.exe")
    )) {
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            $evidence++
        }
    }
    if (Test-LauncherTargetsRoot -Root $Root) {
        $evidence += 2
    }
    if ($evidence -ge 2) {
        return "QwenPaw"
    }
    return "Foreign"
}

function Get-ScopedProcesses {
    param([string]$Root)

    $result = foreach ($process in @(Get-CimInstance Win32_Process)) {
        $path = Get-NormalizedPath -Path "$($process.ExecutablePath)"
        if (Test-PathBelowRoot -Path $path -Root $Root) {
            @{
                Name = "$($process.Name)"
                ProcessId = $process.ProcessId
                CreationDate = "$($process.CreationDate)"
                ExecutablePath = $path
            }
        }
    }
    return @($result)
}

function Test-IsKnownProcess {
    param(
        [object]$Process,
        [string]$Root
    )

    $relative = $Process.ExecutablePath.Substring($Root.Length).TrimStart("\")
    if ($relative -ieq "qwenpaw-desktop.exe" -or
        $relative -ieq "qwenpaw-computer-use-helper.exe") {
        return $true
    }
    foreach ($prefix in @(
        "binaries\qwenpaw-backend\",
        "binaries\python-runtime\",
        "binaries\node-runtime\"
    )) {
        if ($relative.Length -ge $prefix.Length -and
            $relative.Substring(0, $prefix.Length) -ieq $prefix) {
            return $true
        }
    }
    return $false
}

function Stop-ProcessRecords {
    param([object[]]$Processes)

    $ids = @($Processes | ForEach-Object { $_.ProcessId } | Sort-Object -Unique)
    foreach ($processId in $ids) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
    if ($ids.Count -gt 0) {
        Wait-Process -Id $ids -Timeout 8 -ErrorAction SilentlyContinue
    }
}

function Save-UnknownProcesses {
    param([object[]]$Processes)

    if (-not $StateFile) {
        throw "A state file is required to confirm unknown processes."
    }
    @{ Processes = @($Processes) } |
        ConvertTo-Json -Compress -Depth 3 |
        Set-Content -LiteralPath $StateFile -Encoding UTF8
}

function Stop-ConfirmedUnknownProcesses {
    param([string]$Root)

    if (-not $StateFile -or
        -not (Test-Path -LiteralPath $StateFile -PathType Leaf)) {
        throw "The process confirmation expired; retry the scan."
    }
    $saved = Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json
    $confirmed = foreach ($record in @($saved.Processes)) {
        $processId = "$($record.ProcessId)"
        if ($processId -notmatch "^[0-9]+$") {
            continue
        }
        $current = Get-CimInstance Win32_Process -Filter "ProcessId = $processId"
        if ($null -eq $current) {
            continue
        }
        $currentPath = Get-NormalizedPath -Path "$($current.ExecutablePath)"
        $sameCreation = (
            -not "$($record.CreationDate)" -or
            "$($current.CreationDate)" -eq "$($record.CreationDate)"
        )
        if ($currentPath -ieq "$($record.ExecutablePath)" -and
            $sameCreation -and
            (Test-PathBelowRoot -Path $currentPath -Root $Root)) {
            @{ ProcessId = $current.ProcessId }
        }
    }
    Stop-ProcessRecords -Processes @($confirmed)
}

function Write-UnknownProcessList {
    param(
        [object[]]$Processes,
        [string]$Root
    )

    foreach ($process in @($Processes | Sort-Object ExecutablePath, ProcessId)) {
        $relative = $process.ExecutablePath.Substring($Root.Length).TrimStart("\")
        Write-Output "$($process.Name) (PID $($process.ProcessId)): $relative"
    }
}

try {
    if ($Action -eq "Restore") {
        $requestedRoot = (Get-NormalizedPath -Path $InstallDir).TrimEnd("\")
        Restore-NativeHostLauncher -Root $requestedRoot
        if ($StateFile -and (Test-Path -LiteralPath $StateFile)) {
            Remove-Item -LiteralPath $StateFile -Force
        }
        exit 0
    }

    $root = Get-InstallRoot
    $installState = Get-InstallState -Root $root
    if ($installState -eq "Fresh") {
        exit 0
    }
    if ($installState -eq "Foreign") {
        exit 3
    }

    Enable-NativeHostGate -Root $root
    $scoped = Get-ScopedProcesses -Root $root
    $known = @($scoped | Where-Object { Test-IsKnownProcess -Process $_ -Root $root })
    Stop-ProcessRecords -Processes $known

    if ($TerminateUnknown) {
        Stop-ConfirmedUnknownProcesses -Root $root
    }

    $remaining = Get-ScopedProcesses -Root $root
    $knownRemaining = @(
        $remaining | Where-Object { Test-IsKnownProcess -Process $_ -Root $root }
    )
    if ($knownRemaining.Count -gt 0) {
        Write-Output "QwenPaw processes could not be stopped."
        exit 1
    }

    $unknown = @(
        $remaining | Where-Object {
            -not (Test-IsKnownProcess -Process $_ -Root $root)
        }
    )
    if ($unknown.Count -gt 0) {
        Save-UnknownProcesses -Processes $unknown
        Write-UnknownProcessList -Processes $unknown -Root $root
        exit 2
    }

    if ($StateFile -and (Test-Path -LiteralPath $StateFile)) {
        Remove-Item -LiteralPath $StateFile -Force
    }
    exit 0
} catch {
    Write-Output $_.Exception.Message
    exit 1
}
