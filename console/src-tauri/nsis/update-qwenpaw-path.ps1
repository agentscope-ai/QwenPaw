param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Add", "Remove")]
    [string] $Action,

    [Parameter(Mandatory = $true)]
    [string] $Path
)

$ErrorActionPreference = "Stop"

function Normalize-PathEntry {
    param([string] $Value)
    return $Value.Trim().TrimEnd('\', '/')
}

function Broadcast-EnvironmentChange {
    if (-not ("Win32.NativeMethods" -as [type])) {
        Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

namespace Win32 {
    public static class NativeMethods {
        [DllImport("user32.dll", SetLastError=true, CharSet=CharSet.Auto)]
        public static extern IntPtr SendMessageTimeout(
            IntPtr hWnd,
            uint Msg,
            UIntPtr wParam,
            string lParam,
            uint fuFlags,
            uint uTimeout,
            out UIntPtr lpdwResult);
    }
}
"@
    }

    $result = [UIntPtr]::Zero
    [void] [Win32.NativeMethods]::SendMessageTimeout(
        [IntPtr] 0xffff,
        0x001a,
        [UIntPtr]::Zero,
        "Environment",
        0x0002,
        5000,
        [ref] $result
    )
}

$target = Normalize-PathEntry $Path
if (-not $target) {
    exit 0
}

$environment = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey(
    "Environment",
    $true
)
if ($null -eq $environment) {
    $environment = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey(
        "Environment"
    )
}

$current = [string] ($environment.GetValue("Path", "", "DoNotExpandEnvironmentNames"))
$valueKind = [Microsoft.Win32.RegistryValueKind]::ExpandString
try {
    $valueKind = $environment.GetValueKind("Path")
} catch {
    $valueKind = [Microsoft.Win32.RegistryValueKind]::ExpandString
}

$entries = @()
if ($current) {
    $entries = $current -split ';' |
        ForEach-Object { Normalize-PathEntry $_ } |
        Where-Object { $_ }
}

$entries = @(
    $entries |
        Where-Object {
            -not [string]::Equals(
                $_,
                $target,
                [StringComparison]::OrdinalIgnoreCase
            )
        }
)

if ($Action -eq "Add") {
    $entries += $target
}

if ($entries.Count -eq 0) {
    $environment.DeleteValue("Path", $false)
} else {
    $environment.SetValue("Path", ($entries -join ';'), $valueKind)
}

$environment.Close()
Broadcast-EnvironmentChange
