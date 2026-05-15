阿里云CLI支持多款阿里云产品，本文将向您展示如何使用阿里云CLI命令调用常用API，以及如何在OpenAPI门户中生成CLI命令示例。  

## **前置准备**
**重要**

部分 API 涉及资源计费，请在进行调试命令之前确保已经开通所需的云产品，并了解该产品的计费规则以及产品OpenAPI的使用方式。

* 在本地调试命令之前，请确保您已经安装阿里云CLI并正确配置身份凭证信息，详情请参见[安装指南](https://help.aliyun.com/document_detail/121988.html)及[配置凭证](https://help.aliyun.com/document_detail/121193.html)。

* 您可在[OpenAPI门户](https://api.aliyun.com/)中通过产品名获取产品的全部API文档以及对应阿里云CLI命令示例。具体操作请参见[生成命令](#fc9b6069afmg0)。

## 生成命令
**说明**

OpenAPI门户可以在线生成阿里云CLI所有命令，建议您通过此方式获取需要的命令示例。

### 步骤一：登录OpenAPI门户

登录[OpenAPI 门户](https://api.aliyun.com/)。

### 步骤二：查找需生成示例的API

OpenAPI门户提供了多种搜索API方式，您可以选择任意方式完成操作。

## 搜索API名称
**重要**

不同云产品可能存在相同名称的API，请您注意甄别，以防误操作造成损失。

在OpenAPI门户**首页搜索框** 或**顶部搜索框** 中输入目标API名称，单击**去调试**即可跳转至API调试界面。

![image](https://help-static-aliyun-doc.aliyuncs.com/assets/img/zh-CN/8211722371/p820172.png)

## 搜索API所属云产品
1. 在OpenAPI门户**首页搜索框** 或**顶部搜索框** 中输入目标API所属云产品信息，单击**查看API** 即可跳转至**云产品主页**。

![image](https://help-static-aliyun-doc.aliyuncs.com/assets/img/zh-CN/8211722371/p820181.png)

2. 您也可在OpenAPI门户**顶部导航栏** 中单击**选择云产品** ，搜索目标API所属云产品信息并跳转至**云产品主页**。

3. 进入**云产品主页** 后，单击右上角**去调试**，即可跳转至该产品API调试界面。

### 步骤三：生成CLI命令示例

在API调试界面**左侧搜索框** 中可搜索您需要使用的API。在**参数配置** 中根据API文档信息填写参数，单击**参数配置** 右侧的**CLI示例标签页**即可生成携带参数的命令示例。

![image](https://help-static-aliyun-doc.aliyuncs.com/assets/img/zh-CN/8211722371/p820225.png)

* 单击**运行命令** ![image](https://help-static-aliyun-doc.aliyuncs.com/assets/img/zh-CN/7742670271/p820215.png)按钮，可唤出[云命令行](https://help.aliyun.com/document_detail/90256.html)并快速完成命令调试。

* 单击**复制** ![image](https://help-static-aliyun-doc.aliyuncs.com/assets/img/zh-CN/7742670271/p820218.png)按钮，将CLI示例复制到剪贴板中，可粘贴至本地Shell工具中运行。

  * 复制CLI示例到本地Shell工具中进行调试时请注意参数格式。关于阿里云CLI命令参数使用格式的详细信息，请参见[参数格式说明](https://help.aliyun.com/document_detail/110340.html)。

  * OpenAPI门户生成示例中会默认添加`--region`选项，复制命令到本地调用时阿里云CLI将忽略默认身份凭证配置及环境变量设置中的地域信息，优先使用指定的地域调用命令，您可根据需要对该选项进行删除或保留。

## 调用示例
以下代码示例将为您展示如何使用阿里云CLI调用云服务器 ECS中的`CreateInstance`命令，创建一台按量付费ECS实例。获取更多阿里云CLI命令，请参见[生成命令](#fc9b6069afmg0)。

1. 执行命令。

   ```
   HELPCODEESCAPE-shell
   aliyun ecs CreateInstance \
       --InstanceName myvm1 \
       --ImageId centos_7_03_64_40G_alibase_20170625.vhd \
       --InstanceType ecs.n4.small \
       --SecurityGroupId sg-xxxxxx123 \
       --VSwitchId vsw-xxxxxx456 \
       --InternetChargeType PayByTraffic \
       --Password xxx
   ```

2. 输出结果。

   ```
   HELPCODEESCAPE-json
   {
     "RequestId": "473469C7-AA6F-4DC5-B3DB-A3DC0DE3****",
     "InstanceId": "i-bp67acfmxazb4p****",
     "OrderId": "1234567890",
     "TradePrice": 0.165
   }
   ```

3. 您可以通过OpenAPI、SDK或者云服务器 ECS控制台等方式，检查操作是否正确完成。