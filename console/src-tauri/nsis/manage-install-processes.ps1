param(
    [Parameter(Mandatory = $true)]
    [string]$InstallDir,
    [ValidateSet("Prepare", "Restore")]
    [string]$Action = "Prepare",
    [int]$NsisProcessId = 0
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
    return (Get-NormalizedPath -Path $item.FullName).TrimEnd("\")
}

function Test-IsQwenPawInstall {
    param([string]$Root)

    if (-not $Root) {
        return $false
    }
    if (Test-LauncherTargetsRoot -Root $Root) {
        return $true
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
    return $evidence -ge 2
}

function Get-ScopedProcesses {
    param(
        [string]$Root,
        [int]$ExcludedProcessId = 0
    )

    $result = foreach ($process in @(Get-CimInstance Win32_Process)) {
        if ($ExcludedProcessId -gt 0 -and
            $process.ProcessId -eq $ExcludedProcessId) {
            continue
        }
        $path = Get-NormalizedPath -Path "$($process.ExecutablePath)"
        if (Test-PathBelowRoot -Path $path -Root $Root) {
            @{
                Name = "$($process.Name)"
                ProcessId = $process.ProcessId
                CommandLine = "$($process.CommandLine)"
                ExecutablePath = $path
            }
        }
    }
    return @($result)
}

function Test-IsAutomaticProcess {
    param(
        [object]$Process,
        [string]$Root
    )

    $relative = $Process.ExecutablePath.Substring($Root.Length).TrimStart("\")
    if ($relative -ieq "binaries\qwenpaw-backend\qwenpaw-backend.exe" -or
        $relative -ieq "binaries\qwenpaw-backend\qwenpaw.exe") {
        return $true
    }
    $isBundledPython = (
        $relative -ieq "binaries\python-runtime\python\python.exe" -or
        $relative -ieq "binaries\python-runtime\python\pythonw.exe"
    )
    if ($isBundledPython -and
        $Process.CommandLine.ToLowerInvariant().Contains("qwenpaw-nm-host.py")) {
        return $true
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

function Write-ProcessList {
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
        exit 0
    }

    $root = Get-InstallRoot
    if (-not (Test-IsQwenPawInstall -Root $root)) {
        exit 0
    }
    $rootItem = Get-Item -LiteralPath $InstallDir
    if ("$($rootItem.Attributes)" -match "ReparsePoint") {
        throw "Cannot safely manage processes for a reparse-point installation."
    }

    Enable-NativeHostGate -Root $root
    $scoped = Get-ScopedProcesses -Root $root -ExcludedProcessId $NsisProcessId
    $automatic = @(
        $scoped | Where-Object {
            Test-IsAutomaticProcess -Process $_ -Root $root
        }
    )
    Stop-ProcessRecords -Processes $automatic

    $remaining = Get-ScopedProcesses -Root $root -ExcludedProcessId $NsisProcessId
    if ($remaining.Count -gt 0) {
        Write-Output "Close these processes before continuing:"
        Write-ProcessList -Processes $remaining -Root $root
        exit 1
    }
    exit 0
} catch {
    Write-Output $_.Exception.Message
    exit 1
}
