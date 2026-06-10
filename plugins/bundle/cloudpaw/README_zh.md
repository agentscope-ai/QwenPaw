<p align="center">
  <img src="https://raw.githubusercontent.com/agentscope-ai/QwenPaw/main/plugins/bundle/cloudpaw/docs/cloudpaw.png" alt="CloudPaw" width="360" />
</p>

<p align="center">
  <strong>QwenPaw 的云能力增强插件</strong>
</p>

<p align="center">
  <a href="https://github.com/agentscope-ai/CloudPaw/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="License" /></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.10%2B-blue.svg" alt="Python" /></a>
  <a href="#"><img src="https://img.shields.io/badge/version-0.0.3-green.svg" alt="Version" /></a>
</p>

<p align="center">
  <a href="README.md">English</a> | <b>中文</b> | <a href="README_ja.md">日本語</a> | <a href="README_ru.md">Русский</a>
</p>

---

CloudPaw 是 QwenPaw 的云能力增强插件，融合 **QwenPaw + Aliyun CLI** 两大核心组件，并深度集成 **IaC** 能力——它不是简单的聊天机器人，而是一个具备云原生执行引擎的智能助手。

只需用自然语言描述你的需求，CloudPaw 就能自动完成从资源创建到应用部署的全流程。例如：

- **一句话搭建应用**：告诉 CloudPaw "帮我搭建一个个人网站"，它会自动创建 ECS 实例、配置安全组、部署应用并返回可访问的地址。
- **个人站点快速上线**：描述你想要的页面内容和风格，CloudPaw 自动生成代码、部署到云端、绑定公网访问。
- **API 服务快速发布**：指定接口定义，CloudPaw 完成从代码生成、容器构建到服务暴露的整个链路。

CloudPaw 完全部署在您自己的环境中，数据安全可控。

## 快速开始

### 前置要求

| 项目 | 要求 |
|------|------|
| **QwenPaw 版本** | **≥ v1.1.7** |
| **Python** | 3.10 ~ 3.13 |
| **阿里云账号** | 需要 Access Key（用于操作云资源） |

> QwenPaw 的安装方式请参阅 [QwenPaw 快速开始文档](https://qwenpaw.agentscope.io/docs/quickstart)。如果已有 QwenPaw 但版本低于 v1.1.7，请先升级：`pip install --upgrade qwenpaw>=1.1.7`。

### 1. 安装 CloudPaw 插件

**通过控制台安装（推荐）：**

1. 启动 QwenPaw（`qwenpaw app`），打开浏览器访问 http://127.0.0.1:8088/
2. 点击左侧导航栏的 「插件管理」（设置分组下），然后点击 「安装插件」
3. 通过以下任一方式安装：
   - 填入插件下载 URL：`https://qwenpaw-download.oss-ap-southeast-1.aliyuncs.com/files/plugins/cloudpaw/cloudpaw-0.0.3.zip`
   - 将 `cloudpaw/` 文件夹拖拽到安装对话框中，或选择 ZIP 文件（CloudPaw 已预置在 QwenPaw v1.1.7+ 仓库的 `plugins/bundle/cloudpaw/` 目录中）
4. 等待安装完成

**通过命令行安装：**

```bash
qwenpaw plugin install /path/to/cloudpaw
# 或通过 URL 安装
qwenpaw plugin install https://qwenpaw-download.oss-ap-southeast-1.aliyuncs.com/files/plugins/cloudpaw/cloudpaw-0.0.3.zip
```

> **⚠️ 重要提示：安装完成后必须强制刷新浏览器**（`Ctrl+Shift+R` / `Cmd+Shift+R`）以加载前端更新。CloudPaw 的自定义 UI 组件（方案选择、PRD 管理等）在刷新前不会显示。如果安装后发现功能缺失，请先尝试刷新页面。

### 2. 完成必要配置

安装 CloudPaw 后，需要完成以下配置才能正常使用：

#### ① QwenPaw 模型

在控制台 「设置」 → 「模型」 中配置 LLM 提供商和 API Key，详见 [QwenPaw 模型配置文档](https://qwenpaw.agentscope.io/docs/models)。

#### ② 阿里云凭证

在控制台 「环境变量」 中配置（CloudPaw 会自动创建占位条目）：

- `ALIBABA_CLOUD_ACCESS_KEY_ID` — 你的 Access Key ID
- `ALIBABA_CLOUD_ACCESS_KEY_SECRET` — 你的 Access Key Secret
- `ALIBABA_CLOUD_REGION_ID` — 区域 ID（默认 `cn-hangzhou`）

也可通过系统环境变量或命令行配置。

Access Key 的获取方式请参考[阿里云官方文档](https://help.aliyun.com/document_detail/116401.html)。建议使用具有完整权限的主账号 Access Key。

#### ③ iac-code 模型配置

CloudPaw 依赖 [iac-code](https://github.com/aliyun/iac-code)（≥ 0.1.2）生成 IaC 模板。**无需手动配置模型** — CloudPaw 会自动将 QwenPaw 的活跃模型同步给 iac-code。

CloudPaw 插件启动时，会自动在 `~/.iac-code/settings.yml` 中写入 `llm_source: qwenpaw`，iac-code 将直接从 QwenPaw 的活跃模型配置中读取提供商、API Key、模型名称等信息。只要您在 QwenPaw 中已配置好可用的模型（步骤 ①），iac-code 就会自动使用相同的模型，无需额外配置。

**手动覆盖：** 如果需要让 iac-code 使用与 QwenPaw 不同的模型，可设置 `IAC_CODE_PROVIDER` 环境变量（通过 QwenPaw 的「环境变量」页面或系统环境变量）。当该变量存在时，CloudPaw 将跳过自动注入，iac-code 使用您的手动配置。详细配置方式请参阅 [iac-code LLM 配置文档](https://aliyun.github.io/iac-code/docs/configuration/llm-providers)。

### 3. 开始使用

在控制台聊天页面的 Agent 下拉框中选择 「CloudPaw-Master」，即可开始对话。

> **⚠️ 风险提示：请在使用前仔细阅读**
>
> 1. **资源风险警告**：本服务需要使用阿里云管理员凭证，该凭证具有完整的账户访问权限。继续操作可能会对您阿里云账户中的现有资源产生影响，包括创建、修改或删除资源。
> 2. **安全建议**：请务必谨慎操作，并对您账户中的现有资源保持监控。建议在使用前**备份重要数据**，并定期检查资源状态和费用账单。
> 3. **免责声明**：本服务全过程由 AI 驱动，AI 可能会产生错误或不准确的结果。您需要对 AI 执行的操作进行审核和确认，并对最终结果负责。我们不对 AI 操作导致的任何损失承担责任。
> 4. **费用说明**：使用本服务过程中，如果涉及云资源的创建或使用，将会产生相应的云服务费用。请关注您的账单并合理规划资源使用。

## 架构

CloudPaw 通过 QwenPaw 原生插件系统接入。

```
QwenPaw/
└── plugins/
    └── bundle/
        └── cloudpaw/           # CloudPaw 插件（前后端）
            ├── plugin.json     # 插件清单
            ├── plugin.py       # 后端入口
            ├── requirements.txt # Python 依赖（iac-code, httpx-sse）
            ├── ui/             # 前端插件（自定义 tool call 渲染）
            ├── skills/         # 技能定义
            ├── tools/          # 工具实现
            ├── modules/        # 模块
            ├── agents/         # Agent prompt 和配置
            └── prompts/        # Prompt 定义
```

## 功能

- **IaC 部署编排**：通过 [iac-code](https://github.com/aliyun/iac-code) 引擎自动生成 ROS/Terraform 模板，实现阿里云资源自动化部署
- **资源方案选择**：交互式多方案对比和选择，提供专属前端渲染（`proposal_choice` 工具）
- **PRD 管理前端增强**：为 QwenPaw Mission Mode 的 PRD 管理提供自定义前端渲染组件（`manage_prd` 工具）
- **多 Agent 协作**：基于 QwenPaw Mission Mode 编排多个 Agent 协同完成复杂部署任务
- **阿里云 Skills 远程托管能力接入**：通过 A2A 协议连接阿里云 Skills 门户的远程托管 Agent，支持流式实时显示响应进度
- **自动依赖安装**：插件启动时自动安装 `iac-code` 和阿里云 CLI

## 阿里云 Skills 远程托管能力接入

CloudPaw 支持通过 **A2A（Agent-to-Agent）协议** 连接和调用阿里云 Skills 门户中的远程托管 Agent，实现跨 Agent 协作。

> **注意**：当前 A2A 功能仅在 CloudPaw 插件中支持，且仅对阿里云 Skills 远程托管中的 Agent 做支持，连接其他 A2A Agent 可能存在不兼容问题。

### 使用方式

CloudPaw 提供 **两种** 方式调用远程 A2A Agent，两种方式均通过大模型处理并调用 `a2a_call` 工具执行：

#### 方式一：`/a2a` 命令快速调用

在聊天框中使用 `/a2a` 命令向远程 Agent 发送消息：

```
/a2a <别名> <消息内容>
```

示例：

```
/a2a my-agent 如何部署一个 Node.js 应用到 ECS？
```

此命令会被自动改写为大模型可理解的指令，由大模型调用 `a2a_call` 工具完成请求。

#### 方式二：自然语言描述调用

用户直接用自然语言描述需求，大模型会自动判断是否需要调用远程 Agent，并通过 `a2a_call` 工具执行：

```
帮我问问 my-agent，如何快速部署一个 Flask 应用到阿里云？
```

此模式下大模型理解用户意图并自动选择合适的远程 Agent，适合需要多轮对话、上下文关联的场景。

#### 查看已注册 Agent

输入 `/a2a`（不带参数）可列出所有已注册的远程 A2A Agent 及其连接状态，类似于 `/skills` 命令查看已安装的技能。

### 注意事项

- 当前 A2A 功能仅在 CloudPaw 插件中支持，且仅对阿里云 Skills 远程托管中的 Agent 做支持，连接其他 A2A Agent 可能存在不兼容问题
- 调用远程 Agent 时，消息内容会发送至远程服务端，请注意数据安全
- 同一时间仅支持一个活跃的 A2A 调用

## 多 Agent 协作架构

CloudPaw 基于 QwenPaw 的 **Mission Mode** 实现多 Agent 协作。用户只需与主控 Agent 对话，系统会自动将需求拆解为 PRD（产品需求文档），再按 Story 粒度委派给各专业子 Agent 执行。

| Agent | 职责 |
|---|---|
| **CloudPaw-Master** | 主控编排：用户对话、需求澄清、生成 PRD、委派任务、汇总结果 |
| **CloudPaw-Executor** | 通用执行：代码编写、应用部署、环境配置、CLI 操作 |
| **CloudPaw-Verifier** | 统一验证：云资源状态、应用功能、访问性、安全合规 |
| **iac-code**（外部 ACP Agent） | IaC 引擎：通过 ACP 协议异步调用，负责 ROS/Terraform 模板生成、费用估算与资源栈管理 |

## 使用示例

**创建个人主页并部署到云端**

> 帮我创建一个个人主页并上线到云端。页面包含：个人介绍、技能展示、项目经历、联系方式，所有个人信息请先用占位符代替。风格简洁清爽，适配手机和电脑。请使用阿里云 ECS 部署。

**快速发布 API 服务到云端**

> 帮我把一个 API 服务快速发布到云端。我希望默认提供 /health 和 /hello 两个接口，并给我可直接调用的地址和示例请求，配置尽量简单清晰。

## 致谢

- [iac-code](https://github.com/aliyun/iac-code) — 面向阿里云的 AI 基础设施即代码助手
