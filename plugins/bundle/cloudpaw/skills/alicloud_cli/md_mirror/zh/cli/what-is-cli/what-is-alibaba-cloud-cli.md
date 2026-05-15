本文旨在帮助您快速了解阿里云CLI的概念与核心功能。并简要说明其与云产品专用CLI的区别，为您提供清晰的工具选择参考。  

## **前置概念**
阅读本文前，您可能需要了解如下概念：

* [什么是API？](https://help.aliyun.com/document_detail/2669842.html)

* [什么是SDK？](https://help.aliyun.com/document_detail/2669844.html)

## 什么是CLI？
CLI（Command Line Interface）是一种通过文本命令与计算机进行交互的用户界面。用户可以在命令行界面中直接输入指令来执行特定操作，而无需依赖图形用户界面（GUI）。CLI通常用于系统管理、软件开发和网络配置等领域。在计算机领域中，CLI被广泛应用于各种操作系统和软件工具中。

## 什么是阿里云CLI？
阿里云CLI（Alibaba Cloud CLI）是基于[OpenAPI](https://help.aliyun.com/document_detail/2773445.html)构建的通用命令行工具，您可以借助阿里云CLI在命令行界面中对阿里云资源执行增删改查等日常运维任务。

* Linux Shell：在Linux或macOS系统中，使用常见Shell程序（例如[`bash`](https://www.gnu.org/software/bash/)、[`zsh`](http://www.zsh.org/)和[`tcsh`](https://www.tcsh.org/)）来运行命令。

* Windows命令行：在Windows系统中，可以使用命令提示符或PowerShell来运行命令。

* 远程操作：使用[阿里云CloudShell](https://help.aliyun.com/document_detail/102374.html)运行命令，或使用远程终端（例如SSH）通过阿里云ECS实例运行命令。

此外，您还可以基于阿里云CLI开发Shell脚本，用于自动化管理和维护阿里云产品。使用之前，请确保您已经开通了要使用的云产品，并已了解该产品OpenAPI的使用。

如果您在使用中遇到任何问题，可以通过工单或[GitHub Issues](https://github.com/aliyun/aliyun-cli/issues/new)提交反馈，帮助我们共同改进阿里云CLI体验。

## 阿里云CLI与云产品专用CLI（如日志服务CLI）之间有什么区别？
阿里云CLI作为通用命令行工具，其与云产品专用CLI的主要区别在于功能覆盖范围及适用场景的不同。

* 阿里云CLI支持[ECS](https://help.aliyun.com/document_detail/25367.html)、[RDS](https://help.aliyun.com/document_detail/26092.html)、[SLB](https://help.aliyun.com/document_detail/196874.html)等超过100款阿里云产品。用户能够通过统一的命令集，实现跨账号、跨产品对不同资源和服务的管理与操作。适用于需要跨多个产品进行管理和操作的用户，提供基础但广泛适用的功能，适合需要灵活处理多种服务的场景。

* 阿里云云产品专用CLI是指针对特定阿里云产品而设计的命令行工具，如[日志服务CLI](https://help.aliyun.com/document_detail/93539.html)等。这些工具针对特定产品提供了更专业化、更定制化的功能，专注于满足对应产品的复杂场景需求。更适合对某一特定产品有深入需求的用户，提供更为专业化和定制化的功能支持。

## 产品功能
### 云资源管理

阿里云CLI是基于[阿里云OpenAPI](https://help.aliyun.com/document_detail/2773445.html)建立的命令行管理工具。您无需登录控制台，即可通过简洁的命令行方式直接调用各云产品的 OpenAPI，高效管理和维护您的云资源。

### 多产品集成

阿里云CLI集成了[ECS](https://help.aliyun.com/document_detail/25367.html)、[RDS](https://help.aliyun.com/document_detail/26092.html)、[SLB](https://help.aliyun.com/document_detail/196874.html)等100+款阿里云产品的功能。您可在同一命令行界面下完成多个云产品的配置与管理操作，实现统一、便捷的多产品集成体验。

### 多凭证支持

阿里云CLI支持保存和管理多套访问凭证配置。您可以将多个独立的访问密钥和权限策略分别保存至不同配置中，在调用OpenAPI时灵活切换，满足权限分层、环境隔离（如开发、测试、生产）等场景需求，实现更安全、高效的云资源管理。

### 流控退避

阿里云CLI自动启用[基于流控策略的优雅退避机制](https://help.aliyun.com/document_detail/419655.html)，显著减少不必要的重试次数，有效降低系统资源消耗并提高整体操作效率。

### 命令自动补全

阿里云CLI提供Linux和macOS环境下的命令自动补全功能，帮助您快速输入命令参数，无需记忆复杂语法。当前仅支持[`bash`](https://www.gnu.org/software/bash/)、[`zsh`](http://www.zsh.org/)两种Shell环境。

### 多种输出格式

为了便于查看结果或与其他程序协同工作，阿里云CLI支持JSON和table两种输出格式，您可以根据实际需求自由选择。

### 在线帮助

阿里云CLI提供详细的在线帮助功能。通过`help`命令，您可以随时查询当前可用的操作及其支持的参数信息，轻松掌握CLI使用方法。

### 多系统支持

阿里云CLI可安装运行于Windows、macOS和Linux等主流操作系统平台，满足多样化的使用环境需求。

## 相关文档
更多关于阿里云CLI和阿里云OpenAPI相关内容，请参见：

* [GitHub aliyun-cli仓库](https://github.com/aliyun/aliyun-cli)

* [OpenAPI门户](https://api.aliyun.com/)

* [阿里云SDK](https://help.aliyun.com/document_detail/2508482.html)

<br />