本文为您介绍在macOS系统中安装阿里云CLI的操作步骤。  

## **安装步骤**
在macOS系统中，您可以通过以下方式来安装阿里云 CLI。

## 通过PKG安装包安装（推荐）
1. 您可通过以下方式下载macOS系统适用安装包。

   * 下载最新版本：在浏览器中打开下载链接<https://aliyuncli.alicdn.com/aliyun-cli-latest.pkg>下载最新版本的安装包。

   * 下载历史版本：访问[GitHub Release](https://github.com/aliyun/aliyun-cli/releases)页面可查看并下载历史版本安装包。macOS系统适用PKG安装包的包名格式为`aliyun-cli-<version>.pkg`。

2. 双击下载好的安装包，按照说明指引进行操作即可完成安装。

## 通过Homebrew安装
**说明**

在继续操作之前，请确保您已安装并配置[Homebrew](https://brew.sh/)。
1. 修改安装源。（可选）

   中国内地用户可能由于网络问题无法安装，可尝试修改Homebrew安装源以解决此问题。以使用中科大开源镜像站为例：  
   **设置Hombrew安装源为科大源**  
   **说明**

   Homebrew支持通过修改环境变量设置安装源，首次安装Homebrew时也可以通过此方式加速下载过程。

   ```
   HELPCODEESCAPE-bash
   export HOMEBREW_INSTALL_FROM_API=1
   export HOMEBREW_BREW_GIT_REMOTE="https://mirrors.ustc.edu.cn/brew.git"
   export HOMEBREW_CORE_GIT_REMOTE="https://mirrors.ustc.edu.cn/homebrew-core.git"
   export HOMEBREW_BOTTLE_DOMAIN="https://mirrors.ustc.edu.cn/homebrew-bottles"
   export HOMEBREW_API_DOMAIN="https://mirrors.ustc.edu.cn/homebrew-bottles/api"
   brew update
   ```

2. 执行以下命令，安装最新版本的阿里云CLI。

   ```
   HELPCODEESCAPE-bash
   brew install aliyun-cli
   ```

## 通过Bash脚本安装
阿里云CLI提供一键安装脚本，简化安装操作。您可参考以下示例快速安装阿里云CLI。

* 安装最新版本

  若未指定版本，安装脚本将默认获取并安装阿里云CLI的最新可用版本。

  ```
  HELPCODEESCAPE-bash
  /bin/bash -c "$(curl -fsSL https://aliyuncli.alicdn.com/install.sh)"
  ```

* 安装历史版本

  使用`-V`选项可指定阿里云CLI的安装版本。访问[GitHub Release](https://github.com/aliyun/aliyun-cli/releases)页面可查看历史可用版本。

  ```
  HELPCODEESCAPE-bash
  /bin/bash -c "$(curl -fsSL https://aliyuncli.alicdn.com/install.sh)" -- -V 3.0.277
  ```

* 显示使用说明

  使用`-h`选项可在终端中查看阿里云CLI安装脚本的使用说明。

  ```
  HELPCODEESCAPE-bash
  /bin/bash -c "$(curl -fsSL https://aliyuncli.alicdn.com/install.sh)" -- -h
  ```

## 通过TGZ安装包安装
1. 您可以通过以下方式下载安装包。

   * 下载最新版本：

     执行以下命令，下载适用于macOS系统的最新版本安装包。

     ```
     HELPCODEESCAPE-bash
     curl https://aliyuncli.alicdn.com/aliyun-cli-macosx-latest-universal.tgz -o aliyun-cli-macosx-latest-universal.tgz
     ```

   * 下载历史版本：访问[GitHub Release](https://github.com/aliyun/aliyun-cli/releases)页面可下载历史版本安装包。macOS系统适用安装包包名格式为`aliyun-cli-linux-<version>-<architecture>.tgz`。

2. 在安装包所在目录执行以下命令，解压安装包以获取可执行文件`aliyun`。

   ```
   HELPCODEESCAPE-shell
   tar xzvf aliyun-cli-macosx-latest-universal.tgz
   ```

3. 执行以下命令，移动可执行文件至`/usr/local/bin`目录下，实现阿里云CLI的全局调用。

   ```
   HELPCODEESCAPE-bash
   sudo mv ./aliyun /usr/local/bin
   ```

## 验证安装结果
在终端会话中执行如下命令，验证阿里云CLI是否安装成功。  

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

<br />