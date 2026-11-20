param(
    [Parameter(Mandatory = $true)]
    [string]$InstallDir,
    [ValidateSet("Prepare", "Restore", "BeginInstall", "ClearRuntime", "CompleteInstall", "CompleteUninstall", "AbortInstall")]
    [string]$Action = "Prepare",
    [int]$NsisProcessId = 0,
    [switch]$GateCli
)

# Prepare a recognized QwenPaw installation for NSIS replacement. The script
# intentionally uses only cmdlets, operators, and core type methods so it also
# works under WDAC/AppLocker ConstrainedLanguage mode.

$ErrorActionPreference = "Stop"
$gateMarker = "QWENPAW_INSTALL_MAINTENANCE"
$launcher = Join-Path $env:USERPROFILE ".qwenpaw\bin\qwenpaw-nm-host.bat"
$launcherBackup = "$launcher.qwenpaw-maintenance"
$cli = Join-Path $InstallDir "binaries\qwenpaw-backend\qwenpaw.exe"
$cliBackup = "$cli.qwenpaw-maintenance"
$cliStaged = "$cli.qwenpaw-new"
$installMarker = Join-Path $InstallDir ".qwenpaw-installing"

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
    $content = Get-Content -LiteralPath $launcher -Raw
    return ($content -and $content.Contains($gateMarker))
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
        if (-not $content) {
            continue
        }
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
    if ((Test-LauncherTargetsRoot -Root $Root) -or
        (Test-Path -LiteralPath $installMarker -PathType Leaf) -or
        (Test-Path -LiteralPath "$cli.qwenpaw-installing" -PathType Leaf)) {
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
        [int[]]$ExcludedProcessIds = @()
    )

    $result = foreach ($process in @(Get-CimInstance Win32_Process)) {
        if ($ExcludedProcessIds -contains $process.ProcessId) {
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

function Get-NsisProcessIds {
    param([int]$ProcessId)

    if ($ProcessId -le 0) {
        return @()
    }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId"
    return @($ProcessId, $process.ParentProcessId) |
        Where-Object { $_ -gt 0 } |
        Sort-Object -Unique
}

function Test-IsAutomaticProcess {
    param(
        [object]$Process,
        [string]$Root
    )

    $relative = $Process.ExecutablePath.Substring($Root.Length).TrimStart("\")
    if ($relative -ieq "qwenpaw-desktop.exe" -or
        $relative -ieq "binaries\qwenpaw-backend\qwenpaw-backend.exe" -or
        $relative -ieq "binaries\qwenpaw-backend\qwenpaw.exe" -or
        $relative -ieq "binaries\qwenpaw-backend\qwenpaw.exe.qwenpaw-maintenance") {
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

function Assert-RuntimeTree {
    param([object]$Item)

    if ("$($Item.Attributes)" -match "ReparsePoint") {
        throw "Cannot safely replace a linked runtime path: $($Item.FullName)"
    }
    if ($Item.PSIsContainer) {
        foreach ($child in @(Get-ChildItem -LiteralPath $Item.FullName -Force)) {
            Assert-RuntimeTree -Item $child
        }
    }
}

try {
    if ($Action -eq "BeginInstall") {
        # Persist before the first overwrite, including fresh installations.
        # A later installer must not restore an old CLI into a partial update.
        New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
        Set-Content -LiteralPath $installMarker -Value $gateMarker -Encoding Ascii
        # An older uninstaller may have restored the browser launcher.
        Enable-NativeHostGate -Root (Get-InstallRoot)
        exit 0
    }
    if ($Action -eq "ClearRuntime") {
        $root = Get-InstallRoot
        if (-not $root -or -not (Test-Path -LiteralPath $installMarker -PathType Leaf)) {
            throw "Begin installation before replacing bundled runtimes."
        }
        $rootItem = Get-Item -LiteralPath $InstallDir
        if (-not $rootItem.Parent) {
            throw "Cannot replace runtimes at a filesystem root."
        }
        for ($parent = $rootItem; $null -ne $parent; $parent = $parent.Parent) {
            if ("$($parent.Attributes)" -match "ReparsePoint") {
                throw "Cannot safely replace runtimes under a linked installation."
            }
        }
        $binaries = Get-ChildItem -LiteralPath $root -Force |
            Where-Object { $_.Name -eq "binaries" }
        if (-not $binaries) {
            exit 0
        }
        if (-not $binaries.PSIsContainer -or "$($binaries.Attributes)" -match "ReparsePoint") {
            throw "Cannot safely replace runtimes under: $($binaries.FullName)"
        }
        $runtimes = @(Get-ChildItem -LiteralPath $binaries.FullName -Force |
            Where-Object { $_.Name -in @("qwenpaw-backend", "python-runtime", "channel-runtime", "node-runtime") })
        # Validate every tree before deleting any payload; never follow links.
        foreach ($item in $runtimes) {
            if (-not $item.PSIsContainer -or
                -not (Test-PathBelowRoot -Path $item.FullName -Root $root)) {
                throw "Unexpected bundled runtime path: $($item.FullName)"
            }
            Assert-RuntimeTree -Item $item
        }
        foreach ($item in $runtimes) {
            Remove-Item -LiteralPath $item.FullName -Recurse -Force
            if (Test-Path -LiteralPath $item.FullName) {
                throw "Bundled runtime cleanup is incomplete: $($item.FullName)"
            }
        }
        exit 0
    }
    if ($Action -in @("CompleteInstall", "CompleteUninstall")) {
        if ($Action -eq "CompleteInstall") {
            if (Test-Path -LiteralPath $cliStaged) {
                Move-Item -LiteralPath $cliStaged -Destination $cli -Force
            } elseif (-not (Test-Path -LiteralPath $cli)) {
                throw "The new qwenpaw executable is missing. Run the installer again."
            }
        }
        foreach ($path in @($cliBackup, $cliStaged, $installMarker, "$cli.qwenpaw-installing")) {
            if (Test-Path -LiteralPath $path) {
                Remove-Item -LiteralPath $path -Force
            }
        }
        Restore-NativeHostLauncher -Root (Get-InstallRoot)
        exit 0
    }
    if ($Action -eq "AbortInstall") {
        if ((Test-Path -LiteralPath $installMarker) -or
            (Test-Path -LiteralPath "$cli.qwenpaw-installing")) {
            Enable-NativeHostGate -Root (Get-InstallRoot)
            throw "Installation is incomplete. Run the installer again to restore the qwenpaw command."
        }
        if (Test-Path -LiteralPath $cliBackup) {
            Move-Item -LiteralPath $cliBackup -Destination $cli -Force
        }
        Restore-NativeHostLauncher -Root (Get-InstallRoot)
        exit 0
    }
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
    $nsisProcessIds = Get-NsisProcessIds -ProcessId $NsisProcessId
    for ($attempt = 0; $attempt -lt 5; $attempt++) {
        $scoped = Get-ScopedProcesses -Root $root -ExcludedProcessIds $nsisProcessIds
        $automatic = @(
            $scoped | Where-Object {
                Test-IsAutomaticProcess -Process $_ -Root $root
            }
        )
        Stop-ProcessRecords -Processes $automatic

        if (-not $GateCli -or -not (Test-Path -LiteralPath $cli)) {
            break
        }
        try {
            # External version probes can restart the CLI after the sweep.
            # Keep its normal path absent until all new resources are ready.
            Move-Item -LiteralPath $cli -Destination $cliBackup -Force
            break
        } catch {
            if ($attempt -eq 4) {
                throw
            }
            Start-Sleep -Milliseconds 200
        }
    }

    $remaining = Get-ScopedProcesses -Root $root -ExcludedProcessIds $nsisProcessIds
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
