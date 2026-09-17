本文为您介绍更新阿里云CLI的注意事项及操作步骤。  

## **注意事项**
* 为避免版本混淆及潜在的兼容性问题，建议您始终使用与初始安装方法相匹配的更新渠道进行操作。例如：

  * 通过Homebrew安装的阿里云CLI应继续使用Homebrew进行更新，不推荐使用安装包或脚本方式进行升级。

  * 在Linux/macOS上使用自定义安装目录安装的阿里云CLI，推荐使用TGZ安装包手动更新以确保正确覆盖旧版本文件。

* 若您在安装阿里云CLI时使用了自定义安装路径，请在更新版本时指定相同路径，以确保安装路径的一致性。

* 若您更新时存在以下情况，建议您完全[卸载阿里云CLI](https://help.aliyun.com/document_detail/2878717.html)之后，再根据需求重新执行安装操作。

  * 不确定初始安装方式或安装目录。

  * 需要更换为不兼容的安装方式。例如：从脚本安装切换为使用Homebrew安装。

  * 需要修改安装目录。

## 更新步骤
**说明**

操作步骤中`<script_path>`及`<install_path>`均为示例值，执行命令前需替换为实际的脚本文件路径及阿里云CLI安装路径。

### Linux

## 通过Bash脚本更新
执行以下命令，安装最新版本的阿里云CLI。

```
HELPCODEESCAPE-bash
/bin/bash -c "$(curl -fsSL https://aliyuncli.alicdn.com/install.sh)"
```

## 通过TGZ安装包更新
1. 根据系统架构下载安装包。

   **说明**

   您可以执行`uname -m`命令查看Linux系统架构。如果终端输出`arm64`或`aarch64`，表示您的系统架构为ARM64。输出其他信息则表示您的系统架构为AMD64。
   * 执行以下命令，下载适用于Linux AMD64系统的最新版本安装包。

     ```
     HELPCODEESCAPE-bash
     curl https://aliyuncli.alicdn.com/aliyun-cli-linux-latest-amd64.tgz -o aliyun-cli-linux-latest.tgz
     ```

   * 执行以下命令，下载适用于Linux ARM64系统的最新版本安装包。

     ```
     HELPCODEESCAPE-bash
     curl https://aliyuncli.alicdn.com/aliyun-cli-linux-latest-arm64.tgz -o aliyun-cli-linux-latest.tgz
     ```

2. 解压安装包到安装目录，覆盖旧版本文件。

   ```
   HELPCODEESCAPE-bash
   tar xzvf aliyun-cli-latest.tgz -C <install_path>
   ```

### macOS

## 通过PKG安装包更新
1. 在浏览器中访问下载链接<https://aliyuncli.alicdn.com/aliyun-cli-latest.pkg>，下载适用于macOS系统的最新版本PKG安装包。

2. 双击下载好的安装包，按照说明指引进行操作即可完成更新。

## 通过Homebrew更新
1. 修改安装源。（可选）

   中国内地用户可能由于网络问题无法完成更新，可尝试设置Homebrew安装源为国内镜像源以解决此外问题。例如使用中科大开源镜像站：  
   **设置Hombrew安装源为科大源**  
   **说明**

   Homebrew支持通过修改环境变量设置安装源，首次[安装Homebrew](https://brew.sh/)时也可以通过此方式加速下载过程。

   ```
   HELPCODEESCAPE-bash
   export HOMEBREW_INSTALL_FROM_API=1
   export HOMEBREW_BREW_GIT_REMOTE="https://mirrors.ustc.edu.cn/brew.git"
   export HOMEBREW_CORE_GIT_REMOTE="https://mirrors.ustc.edu.cn/homebrew-core.git"
   export HOMEBREW_BOTTLE_DOMAIN="https://mirrors.ustc.edu.cn/homebrew-bottles"
   export HOMEBREW_API_DOMAIN="https://mirrors.ustc.edu.cn/homebrew-bottles/api"
   brew update
   ```

2. 执行以下命令，使用Homebrew更新阿里云CLI。

   ```
   HELPCODEESCAPE-bash
   brew update && brew upgrade aliyun-cli && brew cleanup aliyun-cli
   ```

## 通过Bash脚本更新
执行以下命令，安装最新版本的阿里云CLI。

```
HELPCODEESCAPE-bash
/bin/bash -c "$(curl -fsSL https://aliyuncli.alicdn.com/install.sh)"
```

## 通过TGZ安装包更新
1. 执行以下命令，下载适用于macOS系统的最新版本安装包。

   ```
   HELPCODEESCAPE-bash
   curl https://aliyuncli.alicdn.com/aliyun-cli-macosx-latest-universal.tgz -o aliyun-cli-macosx-latest-universal.tgz
   ```

2. 解压安装包到安装目录，覆盖旧版本文件。

   ```
   HELPCODEESCAPE-bash
   tar xzvf aliyun-cli-macosx-latest-universal.tgz -C <install_path>
   ```

### Windows

## 通过ZIP安装包更新
1. 在浏览器中访问下载链接<https://aliyuncli.alicdn.com/aliyun-cli-windows-latest-amd64.zip>，下载适用于Windows系统的最新版本安装包。

2. 将安装包中的可执行文件`aliyun.exe`解压至阿里云CLI的安装目录，覆盖安装目录中的旧版本文件以完成更新。

   **说明**

   该文件需要通过命令行终端运行，双击文件无法正常工作。

## 通过PowerShell脚本更新
1. 新建脚本文件`Install-CLI-Windows.ps1`，并将下列代码保存至文件中。若您已有此脚本文件，可跳过创建步骤。

   **脚本示例**  

   ```
   HELPCODEESCAPE-powershell
   # Install-CLI-Windows.ps1
   # Purpose: Install Alibaba Cloud CLI on Windows AMD64 systems.
   # Supports custom version and install directory. Only modifies User-level and Process-level PATH.

   [CmdletBinding()]
   param (
       [string]$Version = "latest",
       [string]$InstallDir = "$env:LOCALAPPDATA",
       [switch]$Help
   )

   function Show-Usage {
       Write-Output @"

         Alibaba Cloud Command Line Interface Installer

       -Help                 Display this help and exit

       -Version VERSION      Custom CLI version. Default is 'latest'

       -InstallDir PATH      Custom installation directory. Default is:
                             $InstallDir\AliyunCLI

   "@
   }

   function Write-ErrorExit {
       param([string]$Message)
       Write-Error $Message
       exit 1
   }

   if ($PSBoundParameters['Help']) {
       Show-Usage
       exit 0
   }

   Write-Output @"
   ..............888888888888888888888 ........=8888888888888888888D=..............
   ...........88888888888888888888888 ..........D8888888888888888888888I...........
   .........,8888888888888ZI: ...........................=Z88D8888888888D..........
   .........+88888888 ..........................................88888888D..........
   .........+88888888 .......Welcome to use Alibaba Cloud.......O8888888D..........
   .........+88888888 ............. ************* ..............O8888888D..........
   .........+88888888 .... Command Line Interface(Reloaded) ....O8888888D..........
   .........+88888888...........................................88888888D..........
   ..........D888888888888DO+. ..........................?ND888888888888D..........
   ...........O8888888888888888888888...........D8888888888888888888888=...........
   ............ .:D8888888888888888888.........78888888888888888888O ..............
   "@

   $OSArchitecture = (Get-WmiObject -Class Win32_OperatingSystem).OSArchitecture

   $ProcessorArchitecture = [int](Get-WmiObject -Class Win32_Processor).Architecture

   if (-not ($OSArchitecture -match "64") -or $ProcessorArchitecture -ne 9) {
       Write-ErrorExit "Alibaba Cloud CLI only supports Windows AMD64 systems. Please run on a compatible system."
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
       Write-ErrorExit "Failed to install Alibaba Cloud CLI: $_"
   } finally {
       Remove-Item -Path $DownloadDir -Recurse -Force | Out-Null
   }
   ```

2. 执行以下命令，运行脚本文件以更新阿里云CLI。

   ```
   HELPCODEESCAPE-powershell
   powershell.exe -ExecutionPolicy Bypass -File <script_path> [-InstallDir <install_path>]
   ```