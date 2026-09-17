本文为您介绍在Windows系统中安装阿里云CLI的操作步骤。  

## 安装步骤
**重要**

阿里云CLI当前仅适用于Windows AMD64架构系统，暂不支持32位及其他非AMD64架构（如ARM64）的Windows系统安装阿里云CLI。

在Windows系统中，您可以通过以下方式安装阿里云CLI：

## 通过图形用户界面手动安装
1. 下载安装包

   * 下载最新版本：在浏览器中打开下载链接<https://aliyuncli.alicdn.com/aliyun-cli-windows-latest-amd64.zip>，下载最新版本的安装包。

   * 下载历史版本：访问[GitHub Release](https://github.com/aliyun/aliyun-cli/releases)页面可下载历史版本安装包。Windows系统适用安装包包名格式为`aliyun-cli-windows-<version>-amd64.zip`。

2. 将安装包中的可执行文件`aliyun.exe`解压至您期望的目录，该目录将作为阿里云CLI的安装目录。

   **说明**

   该文件需要通过命令行终端运行，双击文件无法正常工作。
3. 按下`Windows`键+`S`键打开搜索界面，输入搜索关键词"环境变量"。

4. 在搜索结果中单击**编辑账户的环境变量** ，打开**环境变量**设置界面。

5. 在**用户变量** 中选择键为`Path`的环境变量，单击**编辑**。

   ![](https://help-static-aliyun-doc.aliyuncs.com/assets/img/zh-CN/5560987471/p49127.png)
6. 在编辑界面中单击**新建** ，输入阿里云CLI安装目录路径。示例目录：`C:\ExampleDir`（请替换为实际安装目录的路径）。

   ![image](https://help-static-aliyun-doc.aliyuncs.com/assets/img/zh-CN/5560987471/p958791.png)
7. 在所有打开的对话框中依次单击**确定**以保存更改。

8. 重新启动终端会话以使更改生效。

## 通过PowerShell脚本安装
1. 新建脚本文件`Install-CLI-Windows.ps1`，并将下列代码保存至文件中。

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

2. 参考以下示例，运行脚本文件安装阿里云CLI。

   **说明**

   示例脚本路径为`C:\Example\Install-CLI-Windows.ps1`，请将脚本路径替换为实际位置后运行命令。
   * 若未指定版本，安装脚本将默认获取并安装阿里云CLI的最新可用版本。默认安装路径为：`C:\Users\<`***USERNAME***`>\AppData\Local\AliyunCLI`。

     ```
     HELPCODEESCAPE-powershell
     powershell.exe -ExecutionPolicy Bypass -File C:\Example\Install-CLI-Windows.ps1
     ```

   * 使用`-Version`和`-InstallDir`选项可指定阿里云CLI的安装版本和安装目录。访问[GitHub Release](https://github.com/aliyun/aliyun-cli/releases)页面可查看历史可用版本。

     ```
     HELPCODEESCAPE-powershell
     powershell.exe -ExecutionPolicy Bypass -File C:\Example\Install-CLI-Windows.ps1 -Version 3.0.277 -InstallDir "C:\ExampleDir\AliyunCLI"
     ```

   * 使用`-Help`选项可在终端中查看阿里云CLI安装脚本的使用说明。

     ```
     HELPCODEESCAPE-powershell
     powershell.exe -ExecutionPolicy Bypass -File C:\Example\Install-CLI-Windows.ps1 -Help
     ```

## 验证安装结果
重启终端会话后执行如下命令，验证阿里云CLI是否安装成功。

```
HELPCODEESCAPE-shell
aliyun version
```

系统显示类似如下阿里云CLI版本号，表示安装成功。

```
HELPCODEESCAPE-shell
3.0.277
```

<br />