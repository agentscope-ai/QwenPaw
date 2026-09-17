本文将为您介绍使用阿里云CLI调用OpenAPI的具体操作流程，包括安装、配置凭证、生成并调用命令等步骤。  

## **方案概览**
使用阿里云CLI调用OpenAPI，大致分为四个步骤：

1. 安装阿里云CLI：根据您使用设备的操作系统，选择并安装相应的版本。

2. 配置阿里云CLI：在阿里云CLI中完成身份凭证的配置，主要包括AccessKey信息以及地域信息。阿里云CLI将使用配置中的凭证信息调用OpenAPI。

3. 生成CLI命令：在OpenAPI门户中输入参数，生成携带参数的CLI命令示例，复制粘贴到Shell工具中即可运行。

4. 调用API：在Shell工具中输入命令并根据需要使用命令选项，运行命令即可调用对应OpenAPI。

![image](https://help-static-aliyun-doc.aliyuncs.com/assets/img/zh-CN/2466543271/CAEQSBiBgMDSj.vqhRkiIDk3NTAzYjg2OWVmZTQzYTViYzkzYmNmZWJlZDcxNzEy4530473_20240716155803.178.svg)

## 前提条件
* 使用阿里云CLI之前，如果您还没有账号，请访问[阿里云官网](https://www.aliyun.com/)注册阿里云账号（主账号），同时建议您创建专用于API访问的RAM用户。具体操作可参见[创建RAM用户](https://help.aliyun.com/document_detail/93720.html)。

* 部分产品需要开通云产品服务才可调用该产品OpenAPI。您可以通过以下两种方式开通您所需要的云产品服务，以开通短信服务为例：

  * 可访问[开通助手](https://api.aliyun.com/user_center/open)一键开通云产品服务。搜索短信服务，选中短信服务，单击**一键开通**。

  * 访问各云产品控制台开通云产品服务。例如在[短信服务控制台](https://www.aliyun.com/product/sms?spm=5176.21213303.J_qCOwPWspKEuWcmp8qiZNQ.22.28f82f3dxdOwwc&scm=20140722.S_card%40%40%E4%BA%A7%E5%93%81%40%40125575.S_card0.ID_card%40%40%E4%BA%A7%E5%93%81%40%40125575-RL_%E7%9F%AD%E4%BF%A1%E6%9C%8D%E5%8A%A1-LOC_search%7EUND%7Ecard%7EUND%7Eitem-OR_ser-V_3-P0_0)单击**开通**。

* 使用阿里云CLI前，您需要确认需集成的云产品是否支持阿里云CLI。确认方法如下：

  * 查看该云产品文档中心，在**开发参考** \>**集成概览**中查看阿里云CLI支持情况。

  * 在阿里云提供的在线服务[Cloud Shell](https://shell.aliyun.com/)中执行`aliyun --help`命令，获取阿里云CLI支持产品列表。

## 步骤一：安装阿里云CLI
使用阿里云CLI前，您需要先安装阿里云CLI。阿里云CLI为用户提供了Windows、Linux和macOS三种操作系统下的安装服务，请根据您使用设备的操作系统选择对应的安装服务。

* Windows：[在Windows上安装阿里云CLI](https://help.aliyun.com/document_detail/121510.html)。

* Linux：[在Linux上安装阿里云CLI](https://help.aliyun.com/document_detail/121541.html)。

* macOS：[在macOS上安装阿里云CLI](https://help.aliyun.com/document_detail/121544.html)。

您也可使用阿里云提供的云命令行[Cloud Shell](https://shell.aliyun.com/)调试阿里云CLI命令。关于云命令行的更多信息，请参见[什么是云命令行](https://help.aliyun.com/document_detail/90256.html)。

## 步骤二：配置阿里云CLI
**重要**

为保证账号安全，建议您创建专用于API访问的RAM用户并获取身份凭证。更多关于凭证的安全使用建议，请参见[凭证的安全使用方案](https://help.aliyun.com/document_detail/2391595.html)。
使用阿里云CLI之前，您需要在阿里云CLI中配置身份凭证、地域ID等信息。阿里云CLI支持多种身份凭证，详情请参见[身份凭证类型](https://help.aliyun.com/document_detail/121193.html#30ab0f9c3eovm)。本文操作以AK类型凭证为例，具体操作步骤如下：

1. 您需要创建一个RAM用户并根据需要授予管理对应产品的权限。具体操作，请参见[创建RAM用户](https://help.aliyun.com/document_detail/121941.html#task-187540)及[为RAM用户授权](https://help.aliyun.com/document_detail/116146.html)。

2. 创建RAM用户并授权后，您需要创建RAM用户对应的AccessKey，并记录`AccessKey ID`和`AccessKey Secret`，以便后续配置身份凭证使用。具体操作，请参见[创建AccessKey](https://help.aliyun.com/document_detail/116401.html#title-ebf-nrl-l0i)。

3. 您需要获取并记录可用的地域ID，以便后续配置身份凭证使用。阿里云CLI将使用您指定的地域发起API调用，可用地域请参见[地域和可用区列表](https://help.aliyun.com/document_detail/40654.html#title-u71-7kb-w8p)。

   **说明**

   使用阿里云CLI过程中您可使用`--region`选项指定地域发起命令调用，该选项在使用时将忽略默认身份凭证配置及环境变量设置中的地域信息。详情请参见[API命令可用选项](https://help.aliyun.com/document_detail/2822738.html)。
4. 使用RAM用户的AccessKey配置AK类型凭证，配置文件命名为*AkProfile*。具体操作，请参见[配置示例](https://help.aliyun.com/document_detail/121193.html#237984d36ci83)。

## 步骤三：生成CLI命令
**说明**

[OpenAPI门户](https://api.aliyun.com/)可以在线生成阿里云CLI所有命令，建议您通过此方式获取需要的命令示例。若您需要更详细的操作步骤，请参见[生成命令](https://help.aliyun.com/document_detail/110848.html#fc9b6069afmg0)。

在API调试界面**左侧搜索框** 中可搜索您需要使用的API。在**参数配置** 中根据API文档信息填写参数，单击**参数配置** 右侧的**CLI示例**页签即可生成携带参数的命令示例。

![image](https://help-static-aliyun-doc.aliyuncs.com/assets/img/zh-CN/7742670271/p820225.png)
* 单击**运行命令** ![image](https://help-static-aliyun-doc.aliyuncs.com/assets/img/zh-CN/7742670271/p820215.png)按钮，可唤出[云命令行](https://help.aliyun.com/document_detail/90256.html)并快速完成命令调试。

* 单击**复制** ![image](https://help-static-aliyun-doc.aliyuncs.com/assets/img/zh-CN/7742670271/p820218.png)按钮，将CLI示例复制到剪贴板中，可粘贴至本地Shell工具中运行。

  * 复制CLI示例到本地Shell工具中进行调试时请注意参数格式。关于阿里云CLI命令参数使用格式的详细信息，请参见[参数格式说明](https://help.aliyun.com/document_detail/110340.html)。

  * OpenAPI门户生成示例中会默认添加`--region`选项，复制命令到本地调用时阿里云CLI将忽略默认身份凭证配置及环境变量设置中的地域信息，优先使用指定的地域调用命令，您可根据需要对该选项进行删除或保留。

## 步骤四：调用API
### 命令结构

阿里云CLI的通用命令行结构如下。更多详情，请参见[命令结构](https://help.aliyun.com/document_detail/110848.html#1640a5c2c077i)。

```
HELPCODEESCAPE-shell
aliyun <command> <subcommand> [options and parameters]
```

### 常用命令选项

在阿里云CLI中，您可根据需要使用命令行选项，用来修改命令的默认行为或为命令提供额外功能。常用命令行选项如下：

* `--profile `*<profileName>*：使用`--profile`选项并指定有效配置名称*profileName*后，阿里云CLI将忽略默认身份凭证配置及环境变量设置，优先使用指定的配置进行命令调用。

* `--help`：在需要获取帮助的命令层级处键入`--help`选项，即可获取该命令的帮助信息。更多详情，请参见[获取帮助信息](https://help.aliyun.com/document_detail/122046.html)。

更多详细信息，请参见[API命令可用选项](https://help.aliyun.com/document_detail/2822738.html)。

### 调用命令

生成命令后，可复制命令示例并粘贴到Shell工具中运行命令。以如下命令为例，调用云服务器 ECS中的`CreateInstance`命令，创建一台按量付费ECS实例。

```
HELPCODEESCAPE-shell
aliyun ecs CreateInstance
    --InstanceName myvm1
    --ImageId centos_7_03_64_40G_alibase_20170625.vhd
    --InstanceType ecs.n4.small
    --SecurityGroupId sg-xxxxxx123
    --VSwitchId vsw-xxxxxx456
    --InternetChargeType PayByTraffic
    --Password xxx
```

更多命令调用详情，请参见[调用示例](https://help.aliyun.com/document_detail/110848.html#e0a41cfdf4zop)，或各云产品文档中心下的**CLI集成示例**。

<br />