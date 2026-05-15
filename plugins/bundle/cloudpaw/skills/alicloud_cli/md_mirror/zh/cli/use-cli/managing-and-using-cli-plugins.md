阿里云CLI 3.3.0起引入插件化架构，将各云产品的命令行调用能力拆分为独立插件。每个插件对应一个云产品，可按需安装、独立更新，CLI主程序保持轻量。所有插件统一使用短横线（kebab-case）命名风格，并自动处理参数序列化，简化调用体验。  

## 前提条件
1. 已安装阿里云CLI 3.3.0或更高版本。安装方法，请参见[安装CLI（Linux）](https://help.aliyun.com/document_detail/121541.html)。

2. 确保阿里云CLI已配置凭证。配置方法，请参见[配置凭证](https://help.aliyun.com/document_detail/121193.html)。

## 快速开始
以安装`ecs`插件为例，介绍安装插件并查询地域列表的流程。

```
HELPCODEESCAPE-bash
# 安装插件（以ecs插件为例）
aliyun plugin install --names ecs

# 调用API查询地域列表
aliyun ecs describe-regions --accept-language zh-CN
```

可通过`aliyun ecs --help`查看ecs插件支持的所有命令。后续章节将介绍插件命名规则、安装管理、参数用法和进阶特性。

## 插件概述
插件将各云产品的API调用能力封装为独立的可执行程序，由CLI主程序统一调度。主要特性如下：

* **按需安装**：仅安装所需云产品插件，减少CLI体积。

* **独立更新**：插件独立发布版本，无需升级CLI主程序。

* **统一命名** ：命令和参数使用短横线命名，例如`describe-instances`、`--accept-language`。

* **参数简化**：自动处理底层参数序列化，统一使用键值对格式输入。

* **完整帮助**：通过\`--help\`查看参数类型、描述和是否必填。

插件安装在`~/.aliyun/plugins`目录下，清单记录在`manifest.json`文件中。

### 插件命名规则

插件命名格式为`aliyun-cli-<产品Code>`，产品Code与阿里云OpenAPI一致，示例如下：
<table> <thead> <tr> <td><p><b>插件名称</b></p></td> <td><p><b>产品Code</b></p></td> <td><p><b>对应云产品</b></p></td> </tr> </thead> <colgroup></colgroup> <colgroup></colgroup> <colgroup></colgroup> <tbody> <tr> <td><p><code>aliyun-cli-ecs</code></p></td> <td><p><code>ecs</code></p></td> <td><p>云服务器ECS</p></td> </tr> <tr> <td><p><code>aliyun-cli-fc</code></p></td> <td><p><code>fc</code></p></td> <td><p>函数计算FC</p></td> </tr> <tr> <td><p><code>aliyun-cli-rds</code></p></td> <td><p><code>rds</code></p></td> <td><p>云数据库RDS</p></td> </tr> </tbody> </table>

安装、卸载和更新时，使用插件全称（例如`aliyun-cli-ecs`）或产品Code（例如`ecs`），不区分大小写。

## 安装插件
### 查看和搜索插件

查看远程索引中所有可用的插件：

```
HELPCODEESCAPE-bash
aliyun plugin list-remote
```

输出示例：

```
HELPCODEESCAPE-bash
Total plugins available: 316

Name                                     Latest Version  Preview  Status         Local Version  Description
----                                     --------------  -------  ------         -------------  -----------
aliyun-cli-ecs                           0.1.0           No       Installed      0.1.0          Aliyun CLI plugin for Elastic Compute Service operations.
aliyun-cli-fc                            0.1.0           No       Installed      0.1.0          Aliyun CLI plugin for Function Compute 3.0 operations.
aliyun-cli-acc                           0.1.0           No       Not installed  -              Aliyun CLI plugin for acs operations.
```

要查找特定命令所属的插件，可使用搜索功能（支持前缀匹配）：

```
HELPCODEESCAPE-bash
#搜索包含ecs的插件
aliyun plugin search ecs
#搜索ecs产品下以describe开头的命令
aliyun plugin search "ecs describe"
```

**说明**

* CLI 插件遵循语义化版本规范（SemVer）。0.x.x 为实验性版本，不保证兼容性；1.0.0 及以上为稳定版本，同一主版本号内保持向后兼容，主版本号递增可能存在非兼容变更。

* 远程索引默认缓存1小时。如需强制刷新，设置环境变量`ALIBABA_CLOUD_CLI_PLUGIN_NO_CACHE=true`。

### 执行安装

执行以下命令安装插件：

```
HELPCODEESCAPE-bash
aliyun plugin install --names ecs
```

安装完成后，通过`aliyun plugin list`确认结果。

```
HELPCODEESCAPE-bash
Name                Version             Description
----                -------             -----------
aliyun-cli-ecs      0.1.0               Aliyun CLI plugin for Elastic Compute Service operations.
aliyun-cli-fc       0.1.0               Aliyun CLI plugin for Function Compute 3.0 operations.
```

根据需要，可使用以下可选参数：
<table> <thead> <tr> <td><p><b>场景</b></p></td> <td><p><b>示例命令</b></p></td> <td><p><b>说明</b></p></td> </tr> </thead> <colgroup></colgroup> <colgroup></colgroup> <colgroup></colgroup> <tbody> <tr> <td><p>同时安装多个插件</p></td> <td><p><code>aliyun plugin install --names fc ecs</code></p></td> <td><p>多个名称以空格分隔</p></td> </tr> <tr> <td><p>安装指定版本</p></td> <td><p><code>aliyun plugin install --names fc --version 1.0.0</code></p></td> <td><p>不指定则安装最新稳定版</p></td> </tr> </tbody> </table>  
**说明**

CLI自动检测操作系统和架构（例如`darwin-arm64`、`linux-amd64`），下载匹配的插件包。批量安装时，单个插件失败不影响其余插件。部分插件要求最低CLI版本，不满足时会提示升级。

## 使用插件
产品插件统一使用短横线（kebab-case）命名。CLI自动将当前Profile中配置的凭证（AccessKey、STS Token等）、地域和超时设置传递给产品插件。`--profile`和`--region`等选项对插件命令同样生效，无需单独配置。

命令格式：

```
HELPCODEESCAPE-bash
aliyun <产品Code> <命令> [--参数名 值 ...]
```

### 使用示例

#### **查看插件帮助信息**

使用`aliyun <产品Code> --help`或`aliyun <产品Code> <命令> --help`获取帮助信息。例如查看`ecs`所有支持的命令：

```
HELPCODEESCAPE-bash
aliyun ecs --help
```

查看`ecs`插件下特定命令的参数详情：

```
HELPCODEESCAPE-bash
aliyun ecs describe-regions --help
```

输出示例：

```
HELPCODEESCAPE-bash
......
  --accept-language         string, 根据汉语、英语和日语筛选返回结果。更多详情，请参见[RFC
                            7231](https://tools.ietf.org/html/rfc7231)。取值范围：
                            - zh-CN：简体中文。
                            - zh-TW：繁体中文。
                            - en-US：英文。
                            - ja：日文。
                            - fr：法语。
                            - de：德语。
                            - ko：韩语。
                            默认值：zh-CN
  --instance-charge-type    string, 实例的计费方式，更多信息，请参见https://help.aliyun.
                            com/document_detail/25398.html。取值范围：
                            - PrePaid：包年包月。此时，请确认自己的账号支持余额支付或者信用支付，
                            否则将报错InvalidPayMethod。
                            - PostPaid：按量付费。
                            - SpotWithPriceLimit：设置上限价格。
                            - SpotAsPriceGo：系统自动出价，最高按量付费价格。
                            默认值：PostPaid
......
```

帮助信息展示每个参数的类型、描述和是否必填。

#### 查询地域列表

执行以下命令查询地域列表：

```
HELPCODEESCAPE-bash
aliyun ecs describe-regions --accept-language zh-CN
```

查询输出示例：

```
HELPCODEESCAPE-bash
{
  "Regions": {
     "Region": [
{
   "LocalName": "华北1（青岛）",
   "RegionEndpoint": "ecs.cn-qingdao.aliyuncs.com",
   "RegionId": "cn-qingdao"
		},
{
   "LocalName": "华北2（北京）",
   "RegionEndpoint": "ecs.cn-beijing.aliyuncs.com",
   "RegionId": "cn-beijing"
},
......
```

### 进阶用法

#### **结构化参数输入**

插件自动处理底层参数序列化。无论API使用何种参数风格（例如repeatList、flat、json），均使用相同的输入方式：

* 数组参数：当参数（例如`attribute-name`）为数组时，可重复使用特定参数。

  ```
  HELPCODEESCAPE-bash
  aliyun ecs describe-account-attributes\
        --biz-region-id cn-hangzhou\
        --attribute-name max-security-groups\
        --attribute-name instance-network-type
  ```

* 对象参数：当参数（例如`tag`）为对象时，使用`key=value`格式。

  ```
  HELPCODEESCAPE-bash
  aliyun ecs describe-instances --biz-region-id cn-hangzhou\
         --tag key=env value=prod
  ```

#### **多版本API**

部分云产品存在多个API版本。通过`aliyun plugin list`查看已安装插件，描述中包含`multi-version`关键字的插件支持多版本。例如：

```
HELPCODEESCAPE-bash
Name                Version             Description
----                -------             -----------
aliyun-cli-ecs      0.1.0               Aliyun CLI plugin for Elastic Compute Service operations.
aliyun-cli-ess      0.1.0               Aliyun CLI plugin for Auto Scaling operations with multi-version API support.
aliyun-cli-fc       0.1.0               Aliyun CLI plugin for Function Compute 3.0 operations.
```

对于支持多API版本的插件，可使用`--api-version`参数指定API版本：

* 使用默认API版本

  ```
  HELPCODEESCAPE-bash
  aliyun ess describe-scaling-groups --biz-region-id cn-hangzhou
  ```

* 使用`--api-version`指定API版本

  ```
  HELPCODEESCAPE-bash
  aliyun ess describe-scaling-groups --api-version 2022-02-22 --biz-region-id cn-hangzhou
  ```

* 查看支持的API版本列表

  ```
  HELPCODEESCAPE-bash
  aliyun ess list-api-versions 
  ```

如果您经常使用某个特定版本，可通过环境变量设置默认值，避免每次指定`--api-version`。格式为`ALIBABA_CLOUD_<PRODUCT_CODE>_API_VERSION`，其中`<PRODUCT_CODE>`为产品Code大写形式。例如：

```
HELPCODEESCAPE-bash
#添加环境变量并生效
echo 'export ALIBABA_CLOUD_ESS_API_VERSION=2022-02-22' >> ~/.bashrc
source ~/.bashrc
```

设置后直接执行命令即使用该版本。命令中显式指定`--api-version`时，优先级高于环境变量。

## 更新和卸载插件
### 更新插件

更新指定插件：

```
HELPCODEESCAPE-bash
aliyun plugin update --name ecs
```

更新所有已安装的插件：

```
HELPCODEESCAPE-bash
aliyun plugin update
```

如果插件已是最新版本，CLI会提示无需更新。要更新到预发布版本，添加`--enable-pre`参数。

### 卸载插件

```
HELPCODEESCAPE-bash
aliyun plugin uninstall --name ecs
```

操作完成后，通过`aliyun plugin list`确认结果。

## 配置自动安装插件
执行云产品命令时，如果所需插件未安装，CLI可根据配置自动安装。建议在非交互式环境（如 CI/CD、脚本）或经常使用不同云产品时启用，以避免执行中断或反复手动安装插件。

### 启用方式

通过命令启用：

```
HELPCODEESCAPE-bash
aliyun configure set --auto-plugin-install true
```

或通过环境变量启用（以Linux为例配置）：

```
HELPCODEESCAPE-bash
#添加环境变量并生效
echo 'export ALIBABA_CLOUD_CLI_PLUGIN_AUTO_INSTALL=true' >> ~/.bashrc
source ~/.bashrc
```

配置后执行`aliyun configure get`验证。

如需允许自动安装预发布版本：

```
HELPCODEESCAPE-bash
aliyun configure set --auto-plugin-install-enable-pre true
```

或通过环境变量配置（以Linux为例配置）。

```
HELPCODEESCAPE-bash
#添加环境变量并生效
echo 'export ALIBABA_CLOUD_CLI_PLUGIN_AUTO_INSTALL_ENABLE_PRE=true' >> ~/.bashrc
source ~/.bashrc
```

### 安装策略

CLI根据运行环境选择不同策略：
<table> <thead> <tr> <td><p><b>场景</b></p></td> <td><p><b>行为</b></p></td> </tr> </thead> <colgroup></colgroup> <colgroup></colgroup> <tbody> <tr> <td><p>已启用自动安装</p></td> <td><p>自动安装插件并继续执行命令</p></td> </tr> <tr> <td><p>交互式终端且未启用自动安装</p></td> <td><p>提示确认是否安装</p></td> </tr> <tr> <td><p>非交互式环境（脚本、管道）</p></td> <td><p>仅输出安装提示，不自动安装</p></td> </tr> </tbody> </table>

自动安装输出示例：

```
HELPCODEESCAPE-bash
#未安装ecs插件的情况下执行
aliyun ecs describe-regions --accept-language zh-CN
#自动安装过程输出
Plugin 'aliyun-cli-ecs' is required for command 'ecs describe-regions' but not installed.
Auto-installing plugin 'aliyun-cli-ecs' (including pre-release versions)...
Downloading aliyun-cli-ecs 0.1.0...
Plugin aliyun-cli-ecs 0.1.0 installed successfully!
......
```

交互式环境未开启自动安装输出示例：

```
HELPCODEESCAPE-bash
#未安装ecs插件的情况下执行
aliyun ecs describe-regions --accept-language zh-CN
#交互式安装过程输出
Plugin 'aliyun-cli-ecs' is required for command 'ecs describe-regions' but not installed.
Tip: Run 'aliyun configure set --auto-plugin-install true' to skip this prompt.
Do you want to install it? [Y/n]: y
Installing plugin 'aliyun-cli-ecs' (including pre-release versions)...
Downloading aliyun-cli-ecs 0.1.0...
Plugin aliyun-cli-ecs 0.1.0 installed successfully!
......
```

## 附录
### 插件命令列表

<table> <thead> <tr> <td><p><b>命令</b></p></td> <td><p><b>说明</b></p></td> </tr> </thead> <colgroup></colgroup> <colgroup></colgroup> <tbody> <tr> <td><p><code>aliyun plugin list</code></p></td> <td><p>列出已安装插件</p></td> </tr> <tr> <td><p><code>aliyun plugin list-remote</code></p></td> <td><p>列出远程可用插件</p></td> </tr> <tr> <td><p><code>aliyun plugin search \&lt;命令名\&gt;</code></p></td> <td><p>搜索命令对应的插件</p></td> </tr> <tr> <td><p><code>aliyun plugin install --names \&lt;名称\&gt; \[--version \&lt;版本\&gt;\] \[--enable-pre\]</code></p></td> <td><p>安装插件</p></td> </tr> <tr> <td><p><code>aliyun plugin update \[--name \&lt;名称\&gt;\] \[--enable-pre\]</code></p></td> <td><p>更新插件</p></td> </tr> <tr> <td><p><code>aliyun plugin uninstall --name \&lt;名称\&gt;</code></p></td> <td><p>卸载插件</p></td> </tr> </tbody> </table>

### 插件环境变量列表

以下环境变量用于控制插件行为：
<table> <thead> <tr> <td><p><b>环境变量</b></p></td> <td><p><b>说明</b></p></td> </tr> </thead> <colgroup></colgroup> <colgroup></colgroup> <tbody> <tr> <td><p><code>ALIBABA_CLOUD_CLI_PLUGINS_DIR</code></p></td> <td><p>自定义插件目录，默认为<code>\~/.aliyun/plugins</code></p></td> </tr> <tr> <td><p><code>ALIBABA_CLOUD_CLI_PLUGIN_NO_CACHE</code></p></td> <td><p>设为<code>true</code>禁用远程索引缓存</p></td> </tr> <tr> <td><p><code>ALIBABA_CLOUD_CLI_PLUGIN_AUTO_INSTALL</code></p></td> <td><p>设为<code>true</code>启用自动安装</p></td> </tr> <tr> <td><p><code>ALIBABA_CLOUD_CLI_PLUGIN_AUTO_INSTALL_ENABLE_PRE</code></p></td> <td><p>设为<code>true</code>允许自动安装预发布版本</p></td> </tr> <tr> <td><p><code>ALIBABA_CLOUD_\&lt;PRODUCT_CODE\&gt;_API_VERSION</code></p></td> <td><p>设置产品插件默认API版本，例如：<code>ALIBABA_CLOUD_ESS_API_VERSION=2022-02-22</code></p></td> </tr> <tr> <td><p><code>ALIBABA_CLOUD_CLI_MAX_LINE_LENGTH</code></p></td> <td><p>调节参数help信息的单行输出长度。</p></td> </tr> </tbody> </table>

## 常见问题
#### **插件安装提示"no stable version available"**

此提示表示该插件仅提供预发布版本。要安装预发布版本，在安装命令中添加`--enable-pre`参数：

```
HELPCODEESCAPE-bash
aliyun plugin install --names <插件名> --enable-pre
```

<br />

<br />