本文将介绍阿里云CLI的通用命令结构，以及在调用RPC风格或ROA风格OpenAPI时所需的特定命令结构。  

## 通用命令结构
阿里云CLI的通用命令结构如下：

```
HELPCODEESCAPE-shell
aliyun <Command> [SubCommand] [Options and Parameters]
```

结构示例中`Command`、`SubCommand`、`Options and Parameters`的详细信息如下所示：

* `Command`：指定一个顶级命令。

  * 可指定阿里云CLI支持的云产品Code`ProductCode`，例如ecs、rds等。

  * 可指定阿里云CLI本身的功能命令，例如configure等。

<!-- -->

* `SubCommand`：指定要执行操作的子命令，即具体的某一项操作。

  * 当顶级命令`command`为`configure`时，支持的子命令请参见[配置凭证相关命令](https://help.aliyun.com/document_detail/121198.html)。

  * 当顶级命令`command`为云产品Code，且OpenAPI风格为RPC风格时，子命令通常为可调用的OpenAPI名称。

<!-- -->

* `Options and Parameters`：指定用于控制阿里云CLI行为的选项或者OpenAPI参数选项，选项值可以是数字、字符串和JSON结构字符串等。更多参数格式信息，请参见[参数格式](https://help.aliyun.com/document_detail/110340.html)。

## 判断OpenAPI风格
阿里云云产品OpenAPI分为RPC和ROA两种风格类型，大部分产品使用的是RPC风格。不同风格接口的调用方式不同，当您使用阿里云CLI调用接口时需要判断接口类型。您可以通过以下方式判断OpenAPI风格：

* 前往目标云产品文档，单击**开发参考** \> **API概览**，在文档中查看云产品支持的OpenAPI风格。

* 在阿里云CLI中，通过在云产品Code`ProductCode`后使用`--help`选项可以获取产品可用OpenAPI列表，不同风格接口显示的帮助信息存在差异。

  * RPC风格OpenAPI将在帮助信息中显示接口简述。

  * ROA风格OpenAPI将在帮助信息中显示访问路径`PathPattern`。

  更多信息，请参见[获取产品可用API列表](https://help.aliyun.com/document_detail/122046.html#bba9bfc3bb6n4)。
* 在阿里云CLI中，通过在接口名称`APIName`后使用`--help`选项可以获取OpenAPI参数详情。ROA风格OpenAPI会在帮助信息中额外显示接口的请求方式`Method`和访问路径`PathPattern`。更多信息，请参见[获取API参数详情](https://help.aliyun.com/document_detail/122046.html#6f830ae763a38)。

一般情况下，每个产品内所有接口的调用风格是统一的，且每个接口仅支持特定的一种风格。更多关于RPC风格和ROA风格的信息，请参见[OpenAPI 风格](https://help.aliyun.com/document_detail/2618403.html)。

## RPC风格命令结构
### 结构说明

在阿里云CLI中，调用RPC风格的OpenAPI时，其命令结构如下。

```
HELPCODEESCAPE-shell
aliyun <ProductCode> <APIName> [Parameters]
```

示例中`ProductCode`、`APIName`、`Parameters`的详细信息如下所示：

* `ProductCode`：云产品Code。例如云服务器 ECS（Elastic Compute Service）的云产品Code为`ecs`。

* `APIName`：接口名称。例如使用云服务器 ECS的`DescribeRegions`接口。

* `Parameters`：请求参数。您可以在帮助信息或官网文档中查看可用请求参数，以选项形式指定参数。

* 可使用`--help`选项获取关于以上参数的帮助信息。详情请参见[获取帮助信息](https://help.aliyun.com/document_detail/122046.html)。

### 命令示例

* 以下示例为您展示如何调用云服务器 ECS`DescribeRegions`接口，查询可用地域信息列表。更多信息，请参见[DescribeRegions - 查询地域列表](https://help.aliyun.com/document_detail/2679950.html)。

  ```
  HELPCODEESCAPE-shell
  aliyun ecs DescribeRegions
  ```

* 以下示例为您展示如何调用云服务器 ECS`DescribeInstanceAttribute`接口，查询指定ECS实例的属性信息。更多信息，请参见[DescribeInstanceAttribute - 查询实例属性信息](https://help.aliyun.com/document_detail/2679700.html)。

  ```
  HELPCODEESCAPE-shell
  aliyun rds DescribeInstanceAttribute --InstanceId 'i-uf6f5trc95ug8t33****'
  ```

## ROA风格命令结构
### 命令结构

在阿里云CLI中，调用ROA风格OpenAPI时，基本命令结构如下。

```
HELPCODEESCAPE-shell
 aliyun <ProductCode> <Method> <PathPattern> [RequestBody] [Parameters]
```

示例中`ProductCode`、`Method`、`PathPattern`、`RequestBody`、`Parameters`的详细信息如下所示：

* `ProductCode`：云产品Code。例如容器服务 Kubernetes 版 ACK（Container Service for Kubernetes）的云产品Code为`cs`。

* `Method`：请求方式。您可以根据帮助信息或官网文档选择正确的请求方式。常用请求方式有`GET`、`PUT`、`POST`、`DELETE`。

* `PathPattern`：请求路径。您可以根据帮助信息或官网文档选择正确的请求路径。

* `RequestBody`：请求主体。您可以参考帮助信息或官网文档，使用以下选项指定请求主体。

  * 使用`--body`选项指定字符串或变量作为请求主体。

  * 使用`--body-file`选项指定文件路径，将目标文件作为请求主体。

  具体操作请参见[API命令可用选项](https://help.aliyun.com/document_detail/2822738.html)。
* `Parameters`：请求参数。您可以在帮助信息或官网文档中查看可用请求参数，以选项形式指定参数。

* 可使用`--help`选项获取关于以上参数的帮助信息。详情请参见[获取帮助信息](https://help.aliyun.com/document_detail/122046.html)。

### 命令示例

## GET请求
以下示例为您展示如何调用容器服务 Kubernetes 版`DescribeClustersForRegion`接口，查询杭州地域下的ACK专有集群。更多信息，请参见[DescribeClustersForRegion - 查询指定地域的集群列表](https://help.aliyun.com/document_detail/2858150.html)。

```
HELPCODEESCAPE-shell
aliyun cs GET /regions/cn-hangzhou/clusters --cluster_type Kubernetes
```

## PUT请求
以下示例为您展示如何调用容器服务 Kubernetes 版`ModifyCluster`接口，修改集群绑定的EIP实例。更多信息，请参见[ModifyCluster - 修改集群配置](https://help.aliyun.com/document_detail/2667905.html)。

```
HELPCODEESCAPE-shell
aliyun cs PUT /api/v2/clusters/cb95aa626a47740afbf6aa099b65**** --body "{\"api_server_eip\":true,\"api_server_eip_id\":\"eip-wz9fnasl6dsfhmvci****\"}"
```

## POST请求
以下示例为您展示如何调用容器服务 Kubernetes 版`CreateCluster`接口，根据`create.json`文件创建ACK专有集群。更多信息，请参见[CreateCluster - 创建集群](https://help.aliyun.com/document_detail/2667894.html)。

```
HELPCODEESCAPE-shell
aliyun cs POST /clusters --body-file create.json
```

**JSON文件示例**  

```
HELPCODEESCAPE-json
{
    "cluster_type":"Kubernetes",
    "name":"webService",
    "region_id":"cn-beijing",
    "disable_rollback":true,
    "timeout_mins":60,
    "kubernetes_version":"1.14.8-aliyun.1",
    "snat_entry":true,
    "endpoint_public_access":true,
    "ssh_flags":true,
    "cloud_monitor_flags":true,
    "deletion_protection":false,
    "node_cidr_mask":"26",
    "proxy_mode":"ipvs",
    "tags":[],
    "addons":[{"name":"flannel"},{"name":"arms-prometheus"},{"name":"flexvolume"},{"name":"alicloud-disk-controller"},{"name":"logtail-ds","config":"{"IngressDashboardEnabled":"false"}"},{"name":"ack-node-problem-detector","config":"{"sls_project_name":""}"},{"name":"nginx-ingress-controller","config":"{"IngressSlbNetworkType":"internet"}"}],
    "os_type":"Linux",
    "platform":"CentOS",
    "node_port_range":"30000-32767",
    "key_pair":"sian-sshkey",
    "cpu_policy":"none",
    "master_count":3,
    "master_vswitch_ids":["vsw-2zete8s4qocqg0mf6****","vsw-2zete8s4qocqg0mf6****","vsw-2zete8s4qocqg0mf6****"],
    "master_instance_types":["ecs.n4.large","ecs.n4.large","ecs.n4.large"],
    "master_system_disk_category":"cloud_ssd",
    "master_system_disk_size":120,
    "runtime":{"name":"docker","version":"18.09.2"},
    "worker_instance_types":["ecs.i1.xlarge"],
    "num_of_nodes":1,
    "worker_system_disk_category":"cloud_efficiency",
    "worker_system_disk_size":120,
    "vpcid":"vpc-2zecuu62b9zw7a7q****",
    "worker_vswitch_ids":["vsw-2zete8s4qocqg0mf6****"],
    "container_cidr":"172.20.0.0/16",
    "service_cidr":"172.21.0.0/20"
}
```

## DELETE请求
以下示例为您展示如何调用容器服务 Kubernetes 版`DeleteClusterNodepool`接口，删除集群中的指定节点池。更多信息，请参见[DeleteClusterNodepool - 删除节点池](https://help.aliyun.com/document_detail/2667914.html)。

```
HELPCODEESCAPE-shell
aliyun cs DELETE /clusters/cb95aa626a47740afbf6aa099b65****/nodepools/np30db56bcac7843dca90b999c8928****
```