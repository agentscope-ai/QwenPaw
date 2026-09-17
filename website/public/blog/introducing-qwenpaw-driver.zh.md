---
title: "QwenPaw Driver：统一的外部能力接入层"
date: 2026-07-01
author: QwenPaw Team
tags: [外部能力接入, 协议适配, 访问控制, MCP]
excerpt: "Agent 系统正在快速演进。今天的 Agent 不再局限于调用几个内置工具——它需要对接 MCP Server、远程 Agent (A2A)、ACP 服务，以及未来更多的外部协议。"
---

# QwenPaw Driver：统一的外部能力接入层

## 为什么要做 Driver

Agent 系统正在快速演进。今天的 Agent 不再局限于调用几个内置工具——它需要对接 MCP Server、远程 Agent (A2A)、ACP 服务，以及未来更多的外部协议。

这些能力在**通信方式**（stdio / HTTP / WebSocket）、**认证机制**（静态 Token / OAuth2 / AK/SK）和**协议格式**（JSON-RPC / REST / gRPC）上各不相同。如果 Agent 直接耦合这些差异，每新增一种外部能力就要修改 Agent 核心代码。这违反了 Open-Closed 原则，也让系统的安全治理变得碎片化。

我们需要回答一个根本问题：**Agent 系统应该如何感知和管理异构的外部能力？**

## Driver 是什么

> **Driver 将对外部能力的访问抽象为统一的、协议无关的资源模型，使 Agent 系统可以统一地声明（Declarative）、调用（Invocable）和治理（Governable）。**

三个关键词定义了 Driver 的价值：

- **可声明** — 系统知晓哪些外部能力存在、如何到达
- **可调用** — 通过标准接口发起调用，屏蔽底层协议差异
- **可治理** — 控制谁在什么条件下可以调用，精确到单个工具

Driver 不拥有外部服务。外部服务独立存在、独立部署、拥有自己的生命周期。Driver 抽象的是**连接与调用**，而非服务本身。

MCP 是我们交付的第一个具体协议实现。A2A、ACP 等后续协议通过 `register_handler_type()` 即可扩展接入。

## 架构概览

Driver Layer 由五个核心组件构成：

| 组件                 | 职责                                                                   |
| -------------------- | ---------------------------------------------------------------------- |
| **DriverCard**       | Driver 的档案：记录身份、协议、端点、凭证引用、访问策略                |
| **DriverHandler**    | Driver 的执行器：策略裁决 → 协议执行                                   |
| **DriverCapability** | 协议操作的统一抽象：将 Handler 暴露的能力描述为 Agent 可消费的标准格式 |
| **Access Policy**    | 多维裁决引擎：Subject × Principal × Target × Condition → Effect        |
| **DriverManager**    | 集中管理器：类型注册 + 实例构建 + Capability 调度                      |

```
┌────────────────────────────────────────────────────────────────┐
│                        Driver Layer                             │
│                                                                │
│  DriverManager ──builds──▶ DriverHandler                       │
│       │                         │                              │
│       │ reads/persists          │ holds ref                    │
│       ▼                         ▼                              │
│  ┌─────────────────────────────────────────────────────┐       │
│  │ DriverCard (YAML)                                    │       │
│  │ name · protocol · endpoint · credentials · policy    │       │
│  └─────────────────────────────────────────────────────┘       │
│                                                                │
│  Capability: capability_id + kind + action + schema            │
│  Access Policy: ABAC (Subject × Principal × Target → Effect)   │
└────────────────────────────────────────────────────────────────┘
                          ▲ invoke_capability()
                          │
┌─────────────────────────┴──────────────────────────────────────┐
│ Agent Runtime                                                   │
│   build_agent() → Toolkit: [DriverCapabilityTool(cap, invoker)] │
│   LLM → tool_call → invoker → Handler → 协议执行 → 结果返回    │
└─────────────────────────────────────────────────────────────────┘
```

## 核心设计决策

### 1. Card 与 Handler 分离

DriverCard 是纯静态声明（YAML 文件），Handler 是运行时实例。这个分离带来三个好处：

- Card 可版本控制、人类可审计
- Handler 可独立重建而不丢失配置
- 同一 Card 格式可对接不同的 Handler 实现

### 2. 治理管线不可绕过

所有调用必经 `_authorize_invocation()` 治理管线——先裁决访问策略，再执行协议操作。这不是一个可选的中间件，而是**内嵌于 Handler 调用路径的强制约束**。

```
invoke_capability()
  └─ _authorize_invocation()     ← 必经
       ├─ evaluate_policy(ctx)   → allow / deny / ask
       └─ _request_approval(ctx) → 委托给 ApprovalGate（ask 时）
  └─ protocol_execute(...)       ← policy 通过后才执行
```

### 3. Capability URI 统一标识

每个 capability 通过 URI 唯一标识，跨会话可持久引用：

```
driver://{protocol}/{driver_name}/{kind_plural}/{name}#{action}
```

例如：

- `driver://mcp/github-mcp/tools/create_issue#invoke`
- `driver://a2a/translate-agent/agents/translate#invoke`

Agent 不需要知道 capability 来自 MCP 还是 A2A——它只看到统一的 `DriverCapability` 描述和 `invoke_capability()` 入口。

### 4. 凭证四层解耦

凭证管理采用四层架构，实现声明与秘密的完全分离：

```
Layer 1: CredentialRef (Card 中的引用声明)
Layer 2: AsyncCredentialStore (加密存储)
Layer 3: CredentialProvider (解析 + 刷新)
Layer 4: ResolvedCredential (注入 Handler 的运行时凭证)
```

Card 中永远不会出现明文秘密——只有引用。Provider 层支持动态注册，DingTalk/飞书等非标准 OAuth 通过注入自定义 `TokenExchanger` 适配。

### 5. Open-Closed 扩展

新增协议只需三步：

1. 实现 `XxxDriverHandler` — 覆写 `_setup`/`_teardown` + `list_capabilities`/`invoke_capability`
2. 注册：`manager.register_handler_type("xxx", XxxDriverHandler)`
3. 声明：新建 YAML（`protocol: xxx`）

无需修改现有代码。`protocol` 为字符串（非枚举），保证了真正的 Open-Closed。

## Access Policy：精细到每个工具的访问控制

Access Policy 采用 ABAC（基于属性的访问控制）模型，四维裁决：

| 维度      | 映射       | 说明                                          |
| --------- | ---------- | --------------------------------------------- |
| Subject   | 调用者身份 | `user:xxx`、`session:xxx`、`channel:xxx`、`*` |
| Resource  | Target     | `{ kind: "tool", name: "search_issues" }`     |
| Principal | 请求来源   | 来自哪个 channel/app                          |
| Condition | 环境条件   | 时间窗口                                      |

三种裁决效果：

- **allow** — 立即执行
- **deny** — 阻止并返回错误
- **ask** — 挂起等待人工审批（通过注入的 `ApprovalGate` 协议实现）

**优先级裁决**：多条规则匹配时，按 Target 精确度 > Principal 精确度 > Subject 精确度 > 严格程度排序，最具体的规则胜出。

这意味着你可以：

- 默认 `ask` 所有调用，但 `allow` 来自 Console 的 admin 用户
- 对特定危险工具 `deny` 所有人，即使默认策略是 `allow`
- 工作日白天 `allow`，其余时间 `ask`

## Quick Start: MCP Driver

以下是一个完整的 MCP Driver 配置示例，展示如何声明一个带凭证绑定和工具级访问策略的 MCP 服务：

```yaml
# drivers/mcp/hello-mcp.yaml
name: hello-mcp
protocol: mcp
endpoint:
  transport: stdio
  command: python
  args: ["./mcp_servers/hello_server.py"]
  env:
    ECHO_SECRET:
      source: credential
      credential: static
      field: ECHO_SECRET
config:
  display_name: Hello MCP
  description: 本地 stdio MCP 演示服务，提供 print_content 和 get_secret_status 两个工具
enabled: true
policy:
  default_effect: ask
  rules:
    - subject: "*"
      effect: deny
      target: { kind: tool, name: get_secret_status }
```

这份配置做了三件事：

1. **声明连接方式**：通过 stdio 启动本地 Python MCP Server
2. **绑定凭证**：环境变量 `ECHO_SECRET` 从凭证存储中解析注入，Card 中无明文
3. **定义访问策略**：默认所有调用需要审批（`ask`），但 `get_secret_status` 工具被完全禁止（`deny`）

### Console 管理

在 Console 的 **智能体 → MCP** 页面中，点击任意 MCP 客户端卡片上的 **工具&权限** 即可可视化管理访问策略：

![Access Policy 控制台面板](https://img.alicdn.com/imgextra/i1/O1CN01HJgGjv1cQZ0TKGnfC_!!6000000003595-0-tps-3838-2076.jpg)

- 设置客户端级默认效果（Ask / Allow / Deny）
- 为特定来源渠道和用户添加覆盖规则
- 为单个工具设置独立的访问策略
- 保存后立即生效，无需重启

## 端到端调用流程

一次完整的 Driver 调用经历以下阶段：

```
用户请求 → list_capabilities() → build_agent(toolkit)
→ LLM 决策调用工具
→ DriverCapabilityTool.__call__()
→ DriverManager.invoke_capability()
  → parse capability_id → 路由到正确 Handler
  → Handler._authorize_invocation()  [策略裁决]
  → Handler.protocol_execute()       [协议执行]
→ DriverInvocationResult → Agent 继续推理
```

Driver 连接在 Workspace 级别保持持久化（进程内维持 MCP client session），而 Agent 和 Toolkit 则随每次请求重建。这确保了**资源复用**与**隔离安全**之间的平衡。

## 展望

Driver 模块为 QwenPaw Agent 系统建立了统一的外部能力接入基座。当前已交付 MCP 协议支持，A2A 和 ACP 的 Handler 骨架已就绪。未来的演进方向包括：

- **更多协议**：完整的 A2A（Agent-to-Agent）和 ACP 协议实现
- **可观测性**：调用链路追踪、策略裁决审计日志

Driver 的设计哲学是：**让 Agent 专注于推理，让 Driver 处理连接的复杂性。** 无论外部世界的协议如何变化，Agent 看到的始终是统一的 Capability 模型。
