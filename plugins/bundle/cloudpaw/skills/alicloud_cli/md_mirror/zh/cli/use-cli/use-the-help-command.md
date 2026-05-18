阿里云CLI集成了产品和API信息，输入`--help`选项可获取详细的命令帮助信息。  

## **获取支持产品列表及可用命令行选项**
在`aliyun`命令后使用`--help`选项，获取通用命令行选项及支持产品列表。

1. 执行以下命令。

   ```
   HELPCODEESCAPE-shell
   aliyun --help
   ```

2. 预期返回如下信息（部分截取）。

   ```
   HELPCODEESCAPE-plaintext
   shell@Alicloud:~$ aliyun --help
   阿里云CLI命令行工具 3.0.276

   Usage:
     aliyun <product> <operation> [--parameter1 value1 --parameter2 value2 ...]

   Flags:
     --mode                    使用 `--mode {AK|StsToken|RamRoleArn|EcsRamRole|RsaKeyPair|RamRoleArnWithRoleName}` 指定认证方式
     --profile,-p              使用 `--profile <profileName>` 指定操作的配置集
     ...
     --help                    打印帮助信息

   Sample:
     aliyun ecs DescribeRegions

   Products:
     actiontrail                  操作审计
     adb                          云原生数据仓库AnalyticDB MySQL版
     adcp                         分布式云容器平台
     ...
   ```

## 获取产品可用OpenAPI列表
在产品code后使用`--help`选项，可以获取产品可用OpenAPI列表。在列表中，[RPC风格](https://help.aliyun.com/document_detail/2618403.html#4e8af5a00fwyr)的OpenAPI会显示接口的功能描述，而[ROA风格](https://help.aliyun.com/document_detail/2618403.html#871f36600f35h)的OpenAPI则显示对应的访问路径。  
**说明**

阿里云CLI会在接口描述前显示不同的标识，以说明接口的状态或特性，帮助您快速识别接口的使用限制和当前状态：

* 匿名接口：在描述信息前会显示`[Anonymous]`标识，表示该接口无需身份验证即可调用。如需以匿名方式调用该接口，请参见[泛化调用](https://help.aliyun.com/document_detail/2834343.html)。

* 弃用接口：在描述信息前会显示`[Deprecated]`标识，表示该接口已不推荐使用。建议您尽快切换至更新的替代接口。

## RPC风格
1. 执行如下命令，以获取云服务器 ECS（Elastic Compute Service）产品可用OpenAPI列表为例。

   ```
   HELPCODEESCAPE-shell
   aliyun ecs --help
   ```

2. 预期返回如下信息。

   ```
   HELPCODEESCAPE-plaintext
   shell@Alicloud:~$ aliyun ecs --help
   阿里云CLI命令行工具 3.0.276

   Usage:
     aliyun ecs <ApiName> --parameter1 value1 --parameter2 value2 ...

   Product: Ecs (云服务器 ECS)
   Version: 2014-05-26 

   Available Api List: 
     AcceptInquiredSystemEvent                          调用AcceptInquiredSystemEvent接受并授权执行系统事件操作。对问询中（Inquiring）状态的系统事件，接受系统事件的默认操作，授权系统执行默认操作。
     ActivateRouterInterface                            [Deprecated]激活处于Inactive状态的路由器接口。
     AddBandwidthPackageIps                             [Deprecated]
     AddTags                                            添加或者覆盖一个或者多个标签到云服务器ECS的各项资源上。您可以添加标签到实例、磁盘、快照、镜像、安全组等，便于管理资源。
     ...
   ```

## ROA风格
1. 执行如下命令，以获取容器服务 Kubernetes 版 ACK（Container Service for Kubernetes）产品可用OpenAPI列表为例。

   ```
   HELPCODEESCAPE-shell
   aliyun cs --help
   ```

2. 预期返回如下信息。

   ```
   HELPCODEESCAPE-plaintext
   shell@Alicloud:~$ aliyun cs --help
   阿里云CLI命令行工具 3.0.276

   Usage 1:
     aliyun cs [GET|PUT|POST|DELETE] <PathPattern> --body "..." 

   Usage 2 (For API with NO PARAMS in PathPattern only.):
     aliyun cs <ApiName> --parameter1 value1 --parameter2 value2 ... --body "..."

   Product: CS (容器服务Kubernetes版)
   Version: 2015-12-15 

   Available Api List: 
     AttachInstances                         : POST /clusters/[ClusterId]/attach
     AttachInstancesToNodePool               : POST /clusters/[ClusterId]/nodepools/[NodepoolId]/attach
     CancelClusterUpgrade                    : POST /api/v2/clusters/[ClusterId]/upgrade/cancel
     CancelComponentUpgrade                  : POST /clusters/[clusterId]/components/[componentId]/cancel
     ...
   ```

## 获取OpenAPI参数详情
在接口名称后使用`--help`选项，获取OpenAPI可用参数的详细信息，包括参数名称、参数类型等。[ROA风格](https://help.aliyun.com/document_detail/2618403.html#871f36600f35h)OpenAPI会额外显示请求方式及访问路径。

## RPC风格
1. 执行如下命令，以获取云服务器 ECS`DescribeRegions`接口的参数信息为例。

   ```
   HELPCODEESCAPE-shell
   aliyun ecs DescribeRegions --help
   ```

2. 预期返回如下信息。

   ```
   HELPCODEESCAPE-plaintext
   shell@Alicloud:~$ aliyun ecs DescribeRegions --help
   阿里云CLI命令行工具 3.0.276

   Product: Ecs (云服务器 ECS)

   Parameters:
     --AcceptLanguage String  Optional

     根据汉语、英语和日语筛选返回结果。更多详情，请参见[RFC7231](https://tools.ietf.org/html/rfc7231)。取值范围：  
              
     - zh-CN：中文。
     - en-US：英文。
     - ja：日文。
     
     默认值为zh-CN。

     --InstanceChargeType String  Optional

     实例的计费方式，更多详情，请参见[计费概述](~~25398~~)。取值范围：
     
     - PrePaid：包年包月。此时，您必须确认自己的账号支持余额支付或者信用支付，否则将报错InvalidPayMethod。
     - PostPaid：按量付费。
     
     默认值为PostPaid。

     --ResourceType String  Optional

     资源类型。取值范围：
     -  instance：ECS实例
     -  disk：磁盘
     -  reservedinstance：预留实例券
     -  scu：存储容量单位包
     
     默认值：instance
   ```

## ROA风格
1. 执行如下命令，以获取容器服务 Kubernetes 版`AttachInstances`接口的参数信息为例。

   ```
   HELPCODEESCAPE-shell
   aliyun cs AttachInstances --help
   ```

2. 预期返回如下信息。

   ```
   HELPCODEESCAPE-plaintext
   shell@Alicloud:~$ aliyun cs AttachInstances --help
   阿里云CLI命令行工具 3.0.276

   Product:     CS (容器服务Kubernetes版)
   Method:      POST
   PathPattern: /clusters/[ClusterId]/attach

   Parameters:
     --ClusterId String  Required

     集群ID。

     --body Struct  Optional

     请求体参数。
   ```