param(
  [Parameter(Mandatory = $true)]
  [string]$InstallDir
)

$ErrorActionPreference = "SilentlyContinue"

try {
  $installRoot = [System.IO.Path]::GetFullPath($InstallDir).TrimEnd("\") + "\"
} catch {
  exit 0
}

$targets = Get-CimInstance Win32_Process -Filter "Name = 'qwenpaw-backend.exe'" |
  Where-Object {
    if (-not $_.ExecutablePath) {
      return $false
    }

    try {
      $processPath = [System.IO.Path]::GetFullPath($_.ExecutablePath)
    } catch {
      return $false
    }

    return $processPath.StartsWith(
      $installRoot,
      [System.StringComparison]::OrdinalIgnoreCase
    )
  }

$processIds = @($targets | ForEach-Object { $_.ProcessId })

foreach ($processId in $processIds) {
  Stop-Process -Id $processId -Force
}

if ($processIds.Count -gt 0) {
  Wait-Process -Id $processIds -Timeout 8
}

exit 0
