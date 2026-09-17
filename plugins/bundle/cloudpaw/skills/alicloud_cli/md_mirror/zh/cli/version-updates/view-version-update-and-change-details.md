阿里云CLI定期更新，可能包含接口参数调整或其他重要变更。为帮助您快速了解这些变化，本文为您介绍查看阿里云CLI更新内容的操作步骤。  

## **查看主要变更**
阿里云CLI的每个版本都会在GitHub Releases页面中发布对应的变更日志。这里列出了每个版本的新增功能、修复问题、依赖库更新等主要变更。

以查看`v3.0.293`版本的变更为例，具体操作步骤：

1. 访问阿里云CLI的[GitHub Releases](https://github.com/aliyun/aliyun-cli/releases)页面，查找`v3.0.293`版本的发布说明。

2. 在发布说明中，您可以查看类似如下信息：

   * 版本号；

   * 主要变更及对应**commit**链接；

   * 版本对比链接。

   ![image](https://help-static-aliyun-doc.aliyuncs.com/assets/img/zh-CN/1595675571/p994145.png)
3. 如需查看详细变更信息，可单击主要变更后的**commit** 链接，在**Files changed**标签页中查看对应的代码变更。

## 查看API元数据变更
**说明**

本文所述API元数据专为构建阿里云CLI而设计，与通过OpenAPI门户获取的[OpenAPI元数据](https://help.aliyun.com/document_detail/2859170.html)存在差异。该元数据中仅包含CLI所需核心结构信息，不包括详细的API描述、返回值示例或其他辅助信息，且在参数定义上存在简化或差异。

### 在线查看

以查看`v3.0.293`版本对比上一版本的API元数据变更详情为例：

1. 访问阿里云CLI的[GitHub Releases](https://github.com/aliyun/aliyun-cli/releases)页面，查找`v3.0.293`版本的发布说明。

2. 单击**Full Changelog** 后的版本对比链接（例如：`v3.0.292...v3.0.293`），进入GitHub的对比页面。

3. 在该页面中查看`v3.0.293`版本与上一版本之间的`aliyun-openapi-meta`子模块差异。

   该子模块负责管理所有阿里云CLI支持云产品的API元数据定义，需重点关注以下两类关键文件：
   * `metadatas/<PRODUCT_NAME>/<API_Name>.json`

     每个文件对应一个具体的API接口定义，可用于查看：
     * 请求协议（HTTP/HTTPS）、请求方式（GET/POST）等变更；

     * 参数的新增、移除或修改；

     * 参数属性变更：如参数类型、是否必填等。

   * `metadatas/product.json`

     该文件记录阿里云CLI支持的所有云产品信息，可用于查看：
     * 支持云产品的新增或移除；

     * 产品名称、服务接入点的变更；

     * 默认API版本的更新；

     * API风格、API列表等变更。

### 本地对比

除通过GitHub页面查看API变更之外，您还可以在本地环境中导出阿里云CLI的API元数据，通过手动比对或集成自动化流程，与历史版本进行差异分析。

1. 从当前版本中[导出元数据](https://help.aliyun.com/document_detail/2932588.html)。导出元数据中目录结构与GitHub仓库中一致。

2. [更新阿里云CLI](https://help.aliyun.com/document_detail/2877426.html)至目标版本，再次执行导出操作。

3. 对比版本更新前后`metadatas`目录下的元数据差异即可获取API变更信息。

## 元数据结构示例
API元数据文件示例（部分截取）  

```
HELPCODEESCAPE-json
{
  "name": "DescribeInstances",               // API接口名称
  "protocol": "HTTP|HTTPS",                  // 支持的通信协议
  "method": "GET|POST",                      // 支持的请求方式
  "pathPattern": "",                         // 请求路径（若API为RPC风格则值为空）
  "parameters": [                            // 参数列表
    {
      "name": "AdditionalAttributes",        // 参数名称
      "position": "Query",                   // 参数传输位置
      "type": "RepeatList",                  // 数据类型
      "required": false                      // 是否必填
    }
  ]
}
```

云产品元数据文件示例（部分截取）  

```
HELPCODEESCAPE-json
{
  "products": [                                              // 产品列表
    {
      "code": "ECS",                                         // 云产品Code
      "version": "2014-05-26",                               // 默认API版本
      "name": {                                              // 产品名称，支持多语言
        "en": "Elastic Compute Service",                     // 英文名称
        "zh": "云服务器 ECS"                                  // 中文名称
      },
      "location_service_code": "ecs",                        // 用于地域/可用区查询的服务Code，可能与云产品Code不同
      "regional_endpoints": {                                // 支持地域及对应服务接入点列表
        "cn-hangzhou": "ecs-cn-hangzhou.aliyuncs.com"
      },
      "global_endpoint": "",                                 // 全局接入点
      "api_style": "rpc",                                    // API风格
      "apis": [                                              // 当前版本下该产品支持CLI调用的API列表
        "DescribeInstances"
      ]
    }
  ]
}
```