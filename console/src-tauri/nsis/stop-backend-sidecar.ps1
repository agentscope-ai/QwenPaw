param(
    [Parameter(Mandatory = $true)]
    [string]$InstallDir
)

# Stop QwenPaw backend / bundled CLI processes launched from *this* install
# directory so the installer can overwrite their files. A leftover backend
# (possibly orphaned, issue #5550) keeps its PyInstaller ".pyd" modules
# memory-mapped, which locks them on Windows; the installer then fails to
# overwrite those files and shows the cryptic native "can't write file" dialog.
#
# Scoping to $InstallDir leaves a coexisting QwenPaw install untouched.
#
# Must stay ConstrainedLanguage-safe (WDAC/AppLocker): use only cmdlets,
# operators and core string methods -- never [System.*] static calls, which
# throw under ConstrainedLanguage mode and made the previous helper give up
# silently without stopping anything.
#
# Exit 0 when no scoped backend remains, 1 while one is still running.

$ErrorActionPreference = "SilentlyContinue"

$root = $InstallDir.TrimEnd("\") + "\"
$imageNames = @("qwenpaw-backend.exe", "qwenpaw.exe")

function Get-ScopedBackendIds {
    $procs = foreach ($name in $imageNames) {
        Get-CimInstance Win32_Process -Filter "Name = '$name'"
    }
    $scoped = $procs | Where-Object {
        $_.ExecutablePath -and ($_.ExecutablePath -like ($root + "*"))
    }
    return @($scoped | ForEach-Object { $_.ProcessId } | Sort-Object -Unique)
}

$ids = Get-ScopedBackendIds
foreach ($processId in $ids) {
    Stop-Process -Id $processId -Force
}
if ($ids.Count -gt 0) {
    Wait-Process -Id $ids -Timeout 8
}

if ((Get-ScopedBackendIds).Count -gt 0) {
    exit 1
}
exit 0
