本文为您介绍卸载阿里云CLI的注意事项及操作步骤。  

## **注意事项**
* 为避免版本混淆及潜在的兼容性问题，建议您始终使用与初始安装方法相匹配的卸载方式。例如：

  * 通过Homebrew安装的阿里云CLI应优先使用Homebrew进行卸载。不推荐使用其他方式进行升级。

  * 在Linux/macOS上使用自定义安装目录安装的阿里云CLI，推荐通过命令行界面卸载。

* 如果您不确定阿里云CLI的初始安装方式或安装目录，请尝试使用以下所有卸载方法来确保完全卸载。

## 卸载步骤
**说明**

操作步骤中`<script_path>`为示例值，执行命令前需替换为实际的脚本文件路径。

### Linux/macOS

## 通过Homebrew卸载
macOS执行如下命令可卸载阿里云CLI：

```
HELPCODEESCAPE-bash
brew uninstall aliyun-cli
```

## 通过命令行界面卸载
1. 执行以下命令，删除阿里云CLI可执行文件。您也可在图形用户界面中完成此操作。

   ```
   HELPCODEESCAPE-bash
   sudo sh -c "which aliyun | xargs -r rm -v"
   ```

2. 从环境变量PATH中移除安装目录。

   **说明**

   若您在安装阿里云时未使用自定义安装目录，可忽略此步骤。

   Linux/macOS环境下常用的环境变量配置文件如下：
   <table> <thead> <tr> <td><p>Shell类型</p></td> <td><p>配置文件</p></td> </tr> </thead> <colgroup></colgroup> <colgroup></colgroup> <tbody> <tr> <td><p>Bash</p></td> <td> <ul> <li><p><code>\~/.bashrc</code></p></li> <li><p><code>\~/.bash_profile</code></p></li> <li><p><code>\~/.profile</code></p></li> <li><p><code>/etc/profile</code></p></li> </ul></td> </tr> <tr> <td><p>Zsh</p></td> <td> <ul> <li><p><code>\~/.zshrc</code></p></li> <li><p><code>\~/.zprofile</code></p></li> <li><p><code>/etc/zshenv</code></p></li> <li><p><code>/etc/zprofile</code></p></li> <li><p><code>/etc/zshrc</code></p></li> </ul></td> </tr> </tbody> </table>

   您可以使用文本编辑器或命令行工具（如`grep`）搜索与阿里云CLI安装目录相关的改动，并在配置文件中删除或注释相关行。例如，在`~/.bashrc`中查询：

   ```
   HELPCODEESCAPE-bash
   grep "PATH" ~/.bashrc
   ```

## 通过Bash脚本卸载
1. 创建脚本文件，复制以下内容到脚本文件中。

   **脚本示例**  

   ```
   HELPCODEESCAPE-bash
   #!/usr/bin/env bash

   set -euo pipefail

   show_help() {
   cat << EOF

         Alibaba Cloud Command Line Interface Uninstaller

       -h          Display this help and exit

       -C          Remove user config file

   EOF
   }

   abort() {
     printf "%s\n" "$@" >&2
     exit 1
   }

   CLEAN_CONFIG=false

   while getopts ":hC" opt; do
     case "$opt" in
       "h")
         show_help
         exit 0
         ;;
       "C")
         CLEAN_CONFIG=true
         ;;
       *)
         echo "Unexpected flag not supported"
         exit 1
         ;;
     esac
   done

   echo -e "
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
   "

   USER_CONFIG_DIR="${HOME}/.aliyun"
   CONFIG_FILE_PATH="${USER_CONFIG_DIR}/config.json"

   remove_aliyun_binary() {
     local binary
     binary=$(which aliyun)

     if [ -n "$binary" ]; then
       rm -vf "$binary"
       rmdir --ignore-fail-on-non-empty "$(dirname "$binary")" 2>/dev/null || true
     fi
   }

   remove_user_config() {
     if $CLEAN_CONFIG; then
       rm -f "${CONFIG_FILE_PATH}" || abort "Failed to remove config file: ${CONFIG_FILE_PATH}"

       if [ -d "${USER_CONFIG_DIR}" ]; then
         rmdir --ignore-fail-on-non-empty "${USER_CONFIG_DIR}" 2>/dev/null || true
       fi
     fi
   }

   remove_aliyun_binary
   remove_user_config

   echo "Aliyun CLI has been uninstalled."
   ```

2. 参考以下示例，运行脚本以卸载阿里云CLI。

   ```
   HELPCODEESCAPE-bash
   # 仅卸载可执行文件
   bash <script_path>

   # 卸载可执行文件并删除配置文件
   bash <script_path> -C

   # 查看脚本帮助信息
   bash <script_path> -h
   ```

### Windows

Windows用户可通过以下方式卸载阿里云CLI。

## 通过图形用户界面卸载
1. 从文件资源管理器中进入阿里云CLI安装目录，删除阿里云CLI可执行文件。

2. 按下`Windows`键，输入搜索关键词"环境变量"。

3. 在搜索结果中单击**编辑账户的环境变量** ，即可打开**环境变量**设置界面。

4. 在**用户变量** 中选择键为`Path`的环境变量，单击**编辑**。

   ![](https://help-static-aliyun-doc.aliyuncs.com/assets/img/zh-CN/5560987471/p49127.png)
5. 在编辑界面中选中阿里云CLI安装目录路径，单击**删除** ，从环境变量`Path`中移除阿里云CLI安装目录路径。示例目录：`C:\ExampleDir`（请替换为实际安装目录的路径）。

   ![image](https://help-static-aliyun-doc.aliyuncs.com/assets/img/zh-CN/4575631571/p960409.png)
6. 在所有相关对话框中依次单击**确定**以保存更改。

## 通过PowerShell脚本卸载
1. 创建脚本文件，复制以下内容到脚本文件中。

   **脚本示例**  

   ```
   HELPCODEESCAPE-powershell
   # Uninstall-CLI-Windows.ps1
   # Purpose: Automatically detect and uninstall Aliyun CLI, and delete configuration files in user directory

   [CmdletBinding()]
   param (
       [switch]$Clean,
       [switch]$Help
   )

   function Show-Usage {
       Write-Output @"

         Alibaba Cloud Command Line Interface Uninstaller

       -Help                 Display this help and exit

       -Clean                Remove user config file

   "@
   }

   function Remove-DirectoryIfEmpty {
       param([string]$Path)
       if ((Get-ChildItem -Path $Path -Force).Count -eq 0) {
           Remove-Item -Path $Path -Force
       }
   }

   function Remove-AliyunCLIFromPath {
       param([string]$PathToRemove)
       $Key = 'HKCU:\Environment'
       $CurrentPath = (Get-ItemProperty -Path $Key -Name PATH).PATH
       if ($CurrentPath -like "*$PathToRemove*") {
           $newPath = ($CurrentPath -split ';' | Where-Object { $_ -ne $PathToRemove }) -join ';'
           Set-ItemProperty -Path $Key -Name PATH -Value $newPath
           $env:PATH = $newPath
       }
   }

   function Remove-AliyunCLI {
       $AliyunBinary = (Get-Command aliyun -ErrorAction SilentlyContinue).Source
       if ($AliyunBinary -and (Test-Path $AliyunBinary)) {
           Remove-Item -Path $AliyunBinary -Force
           $AliyunInstallDir = Split-Path -Parent $AliyunBinary
           Remove-DirectoryIfEmpty -Path $AliyunInstallDir
           Remove-AliyunCLIFromPath -PathToRemove $AliyunInstallDir
           Write-Output "Aliyun CLI binary has been removed."
       }
   }

   function Remove-ConfigFile {
       $ConfigDir = Join-Path $HOME ".aliyun"
       $ConfigFile = Join-Path $ConfigDir "config.json"
       if (Test-Path $ConfigFile) {
           Remove-Item -Path $ConfigFile -Force
           Remove-DirectoryIfEmpty -Path $ConfigDir
           Write-Output "Aliyun CLI config file has been removed."
       }
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

   try {
       Remove-AliyunCLI
       if ($PSBoundParameters['Clean']) { Remove-ConfigFile }
       Write-Output "Aliyun CLI has been uninstalled."
   } catch {
       Write-Output "Failed to uninstall Aliyun CLI: $_"
   }
   ```

2. 参考以下示例，运行脚本以卸载阿里云CLI。

   ```
   HELPCODEESCAPE-powershell
   # 仅卸载可执行文件
   powershell.exe -ExecutionPolicy Bypass -File <script_path>

   # 卸载可执行文件并删除配置文件
   powershell.exe -ExecutionPolicy Bypass -File <script_path> -Clean

   # 查看脚本帮助信息
   powershell.exe -ExecutionPolicy Bypass -File <script_path> -Help
   ```

## 删除配置文件（可选）
阿里云CLI的配置文件位于您个人用户目录下的`.aliyun`文件夹中，个人用户目录位置因操作系统而异。

* Windows：`C:\Users\<`***USERNAME*** *>*`\.aliyun`

* Linux/macOS：`~/.aliyun`