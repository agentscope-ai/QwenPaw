# ACP 集成

QwenPaw 对 **ACP（Agent Client Protocol）** 提供两种互补的支持方式：

1. **QwenPaw 作为 ACP Server** —— 外部客户端通过 ACP 连接到 QwenPaw
2. **QwenPaw 将 ACP 作为 Tool 使用** —— QwenPaw 连接外部 ACP runner，并把它作为委托协作能力来使用

本页会同时介绍这两种模式，以及各自适合的使用场景。

---

## QwenPaw as ACP Server

在这种模式下，QwenPaw 会通过 stdio JSON-RPC 将自己暴露为一个符合 [Agent Client Protocol (ACP)](https://github.com/agentclientprotocol/python-sdk) 规范的智能体服务。外部客户端（如 [Zed](https://zed.dev)、[OpenCode](https://github.com/nicholasgasior/opencode) 或任何兼容 ACP 的编辑器）可以通过 `qwenpaw acp` 命令连接 QwenPaw，并以编程方式与之交互。

### 快速开始

```bash
# 启动 QwenPaw 作为 ACP 智能体
qwenpaw acp

# 使用指定的智能体配置
qwenpaw acp --agent mybot

# 使用自定义工作区目录
qwenpaw acp --workspace /path/to/workspace

# 启用调试日志（输出到 stderr）
qwenpaw acp --debug
```

进程通过 stdin/stdout 使用 ACP JSON-RPC 协议通信，stderr 用于日志输出。

### 支持的 ACP 方法

| 方法                | 说明                                              |
| ------------------- | ------------------------------------------------- |
| `initialize`        | 握手——返回智能体能力和版本信息                    |
| `new_session`       | 创建新的会话                                      |
| `load_session`      | 按 ID 加载/接入已有会话                           |
| `resume_session`    | 恢复之前关闭的会话                                |
| `list_sessions`     | 列出活跃会话，可按 `cwd` 过滤                     |
| `close_session`     | 关闭并清理会话                                    |
| `prompt`            | 发送用户消息，流式返回智能体响应                  |
| `set_session_model` | 切换活跃 LLM 模型（格式：`provider_id:model_id`） |
| `set_config_option` | 切换会话配置选项（如 Tool Guard 开关）            |
| `cancel`            | 取消正在进行的 prompt                             |

### 流式更新

在 `prompt` 调用过程中，智能体通过 `session_update` 通知向客户端实时推送更新：

| 更新类型              | 触发时机                |
| --------------------- | ----------------------- |
| `agent_message_chunk` | 智能体文本响应（流式）  |
| `agent_thought_chunk` | 智能体内部推理/系统消息 |
| `tool_call`           | 工具调用开始            |
| `tool_call_update`    | 工具执行完成并返回结果  |

### 声明的能力

智能体在 `initialize` 阶段声明以下能力：

```json
{
  "load_session": true,
  "session_capabilities": {
    "close": {},
    "list": {},
    "resume": {}
  }
}
```

### 会话配置选项

创建新会话时，智能体会返回可通过 `set_config_option` 切换的配置选项：

| 配置 ID | 类型   | 类别   | 默认值    | 可选值                                                                        |
| ------- | ------ | ------ | --------- | ----------------------------------------------------------------------------- |
| `mode`  | select | `mode` | `default` | `default` — 正常模式，启用 Tool Guard；`bypassPermissions` — 跳过工具安全检查 |

### 配置

ACP 智能体按以下优先级解析配置：

1. **CLI 参数** —— `--agent` 和 `--workspace` 优先级最高
2. **WORKING_DIR 配置** —— 从 `WORKING_DIR` 内的 `config.json` 中读取 `agents.active_agent`（默认 `~/.qwenpaw`，旧版安装为 `~/.copaw`；可通过 `QWENPAW_WORKING_DIR` 环境变量覆盖）
3. **默认值** —— 回退到智能体 ID `"default"` 和工作区目录 `WORKING_DIR/workspaces/default/`

---

## QwenPaw 将 ACP 作为 Tool 使用

QwenPaw 也可以反过来使用 ACP：不是自己作为 server 被外部客户端连接，而是作为 **ACP client / orchestrator** 去连接**已配置并启用的外部 ACP runner**，并把它们作为委托协作能力接入当前会话。

这类能力的实际调用入口是内置工具 `delegate_external_agent`。它适用于你希望 QwenPaw 与其他支持 ACP 的外部 agent/runtime 协作的场景，例如源码中默认内置的 `opencode`、`qwen_code`、`claude_code`、`codex`。这些 agent 可参考 ACP 官方的 Agent 列表与接入说明：<https://agentclientprotocol.com/get-started/agents>。换句话说，QwenPaw 不是“直接和任意外部 agent 交互”，而是通过 ACP 配置中已注册的 runner，在会话内发起、继续、响应和关闭一次委托式协作。

### 这种模式能做什么

在这种模式下，QwenPaw 会通过内置的 `delegate_external_agent` 工具来：

- 启动一个外部 ACP runner 会话
- 向该 runner 发送后续消息
- 响应该 runner 发起的权限请求
- 在任务完成后关闭委托会话

从概念上看，这让 QwenPaw 可以把一个外部 agent 当作“可协作的工具能力”来使用，同时仍然由 QwenPaw 负责主会话编排。

### 如何配置外部 runner

在使用外部 runner 之前，请先安装一个支持 ACP 协议的外部 agent，并完成登录或 API Key 等必要配置，确保它可以在命令行中正常启动和使用。可参考 ACP 官方提供的 agent 列表：<https://agentclientprotocol.com/get-started/agents>。

![qwen](https://gw.alicdn.com/imgextra/i1/O1CN01XtTTNP1IuyyyKi5ZS_!!6000000000954-2-tps-1196-664.png)

完成命令行侧准备后，你可以在 QwenPaw 中配置自定义 agent，或直接使用内置 agent 与其协作。

外部 runner 需要先在 **Workspace → ACP** 页面中完成配置并启用，之后才能被 `delegate_external_agent` 调用。

当前 ACP 配置页支持为每个 runner 设置以下字段：

- `enabled`
- `command`
- `args`
- `env`
- `trusted`
- `tool_parse_mode`
- `stdio_buffer_limit_bytes`

其中：

- `command` 与 `args` 用于定义外部 runner 的启动方式；
- `env` 用于传递环境变量；
- `tool_parse_mode` 与 `stdio_buffer_limit_bytes` 用于控制 ACP 输出解析方式以及 stdio 缓冲行为。

源码中默认内置了这些 runner 示例：`opencode`、`qwen_code`、`claude_code`、`codex`。你也可以在 ACP 页面中添加自定义 runner，只要它能够以 ACP 方式运行并被正确配置即可。

![config](https://gw.alicdn.com/imgextra/i3/O1CN01pskmLt29VwyFGhO1r_!!6000000008074-2-tps-1224-472.png)

配置完成后，在工具栏中启用 `delegate_external_agent` 工具。

![config](https://gw.alicdn.com/imgextra/i1/O1CN01xNZfYc1OM4UFIR79S_!!6000000001690-2-tps-1224-696.png)

随后，你就可以在对话中明确指定要与哪个外部 agent 进行协作。

![comm](https://gw.alicdn.com/imgextra/i4/O1CN01lk5XhU2988NFcFtR0_!!6000000008022-2-tps-2022-1166.png)

### 典型工作流

一个典型的委托式 ACP 工作流如下：

1. 在 **Workspace → ACP** 页面中配置并启用一个 runner。
2. 在会话中调用 `delegate_external_agent(action="start", runner="...", message="...")`，为该 runner 启动一条新的委托会话。
3. 如果需要继续协作，调用 `delegate_external_agent(action="message", runner="...", message="...")`，向已开启的 runner 会话发送后续消息。
4. 如果外部 runner 发起权限请求，先由用户从界面展示的选项中做出选择，再调用 `delegate_external_agent(action="respond", runner="...", message="<exact option id>")` 恢复执行。这里的 `message` 必须是权限请求中返回的**精确 option id**。
5. 委托任务完成后，调用 `delegate_external_agent(action="close", runner="...")` 关闭该 runner 会话。

你也可以在 `start` 或 `message` 时传入类似“请分析当前工作目录结构”或“请把你的自我介绍写入一个 markdown 文件”这样的任务说明，但底层流程始终对应上述四种 action：`start`、`message`、`respond`、`close`。

### 支持的委托动作

当前委托流程支持以下动作类型：

| 动作      | 用途                                      |
| --------- | ----------------------------------------- |
| `start`   | 启动新的委托 ACP 会话                     |
| `message` | 向已有委托会话发送后续消息                |
| `respond` | 使用选定的 option id 响应待处理的权限请求 |
| `close`   | 关闭委托 ACP 会话                         |

### 权限处理

当外部 ACP runner 请求权限时，QwenPaw **不会替用户做决定**。

相反，它会：

- 暂停当前委托流程
- 展示权限详情和可选项
- 等待用户明确选择如何继续

这样可以让委托式 ACP 执行与 QwenPaw 其他能力保持一致的用户可控安全模型。

### 什么时候使用 ACP as Tool

以下场景适合使用这种模式：

- 你希望 QwenPaw 与另一个 agent runtime 协作
- 你有一个专门处理某类任务的 ACP-compatible 外部 runner
- 你希望由 QwenPaw 作为主控编排者，把部分工作委托给外部 agent

### ACP Tool 与 MCP 的区别

ACP as Tool 和 MCP 解决的问题并不相同：

- **MCP**：让 QwenPaw 连接外部服务和工具服务器
- **ACP as Tool**：让 QwenPaw 连接外部 **agent** runtime

如果你需要接入 API、数据库、文件系统或服务能力，优先使用 **MCP**。
如果你需要 agent 与 agent 之间的协作，优先使用 **ACP as Tool**。

---

## ACP Server vs ACP Tool

| 维度           | QwenPaw as ACP Server            | QwenPaw using ACP as Tool           |
| -------------- | -------------------------------- | ----------------------------------- |
| QwenPaw 的角色 | Server / 被连接的智能体          | Client / 编排者                     |
| 连接方向       | 外部客户端连接 QwenPaw           | QwenPaw 连接外部 runner             |
| 主要目的       | 让编辑器或外部客户端驱动 QwenPaw | 让 QwenPaw 把工作委托给另一个 agent |
| 典型入口       | `qwenpaw acp`                    | delegation tool + ACP runner 配置   |
| 适用场景       | 编辑器集成、程序化控制           | 多智能体协作、外部专用 runner       |

---

## 总结

ACP 在 QwenPaw 中并不是单一能力，而是支持两个方向：

- **向外暴露 QwenPaw**：作为 ACP server
- **从 QwenPaw 向外协作**：把外部 ACP agent 当作委托工具使用

如果你是要把 QwenPaw 接入另一个客户端，优先看 **ACP Server**。
如果你是希望 QwenPaw 去协调另一个 agent runtime，优先看 **ACP as Tool**。
