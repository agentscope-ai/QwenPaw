# Install-CLI-Windows.ps1
# Purpose: Install Alibaba Cloud CLI on Windows AMD64 systems.
[CmdletBinding()]
param (
    [string]$Version = "latest",
    [string]$InstallDir = "$env:LOCALAPPDATA"
)

$OSArchitecture = (Get-WmiObject -Class Win32_OperatingSystem).OSArchitecture
$ProcessorArchitecture = [int](Get-WmiObject -Class Win32_Processor).Architecture
if (-not ($OSArchitecture -match "64") -or $ProcessorArchitecture -ne 9) {
    Write-Error "Alibaba Cloud CLI only supports Windows AMD64 systems."
    exit 1
}

$DownloadUrl = "https://aliyuncli.alicdn.com/aliyun-cli-windows-$Version-amd64.zip"
$tempPath = $env:TEMP
$randomName = -join ((65..90) + (97..122) + (48..57) | Get-Random -Count 8)
$DownloadDir = Join-Path -Path $tempPath -ChildPath $randomName
New-Item -ItemType Directory -Path $DownloadDir | Out-Null

try {
    $InstallDir = Join-Path $InstallDir "AliyunCLI"
    if (-not (Test-Path $InstallDir)) {
        New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    }
    $ZipPath = Join-Path $DownloadDir "aliyun-cli.zip"
    Start-BitsTransfer -Source $DownloadUrl -Destination $ZipPath
    Expand-Archive -Path $ZipPath -DestinationPath $DownloadDir -Force
    Move-Item -Path "$DownloadDir\aliyun.exe" -Destination "$InstallDir\" -Force

    $Key = 'HKCU:\Environment'
    $CurrentPath = (Get-ItemProperty -Path $Key -Name PATH).PATH
    if ([string]::IsNullOrEmpty($CurrentPath)) {
        $NewPath = $InstallDir
    } else {
        if ($CurrentPath -notlike "*$InstallDir*") {
            $NewPath = "$CurrentPath;$InstallDir"
        } else {
            $NewPath = $CurrentPath
        }
    }
    if ($NewPath -ne $CurrentPath) {
        Set-ItemProperty -Path $Key -Name PATH -Value $NewPath
        $env:PATH += ";$InstallDir"
    }
} catch {
    Write-Error "Failed to install Alibaba Cloud CLI: $_"
    exit 1
} finally {
    Remove-Item -Path $DownloadDir -Recurse -Force -ErrorAction SilentlyContinue
}
