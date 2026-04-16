# ACP Server — 将 QwenPaw 作为 ACP 智能体运行

本模块将 QwenPaw 暴露为一个符合 [Agent Client Protocol (ACP)](https://github.com/agentclientprotocol/python-sdk) 规范的智能体服务器，通过 stdio JSON-RPC 通信。外部客户端（如 [Zed](https://zed.dev)、[OpenCode](https://github.com/nicholasgasior/opencode) 或任何兼容 ACP 的编辑器）可以通过 `qwenpaw acp` CLI 命令连接 QwenPaw 并以编程方式与之交互。

---

## 快速开始

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

---

## 支持的 ACP 方法

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

---

## 流式更新

在 `prompt` 调用过程中，智能体通过 `session_update` 通知向客户端实时推送更新：

| 更新类型              | 触发时机                |
| --------------------- | ----------------------- |
| `agent_message_chunk` | 智能体文本响应（流式）  |
| `agent_thought_chunk` | 智能体内部推理/系统消息 |
| `tool_call`           | 工具调用开始            |
| `tool_call_update`    | 工具执行完成并返回结果  |

---

## 声明的能力

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

---

## 会话配置选项

创建新会话时，智能体会返回可通过 `set_config_option` 切换的配置选项：

| 配置 ID | 类型   | 类别   | 默认值    | 可选值                                                                        |
| ------- | ------ | ------ | --------- | ----------------------------------------------------------------------------- |
| `mode`  | select | `mode` | `default` | `default` — 正常模式，启用 Tool Guard；`bypassPermissions` — 跳过工具安全检查 |

---

## 配置

ACP 智能体按以下优先级解析配置：

1. **CLI 参数** — `--agent` 和 `--workspace` 优先级最高
2. **WORKING_DIR 配置** — 从 `WORKING_DIR` 内的 `config.json` 中读取 `agents.active_agent`（默认 `~/.qwenpaw`，旧版安装为 `~/.copaw`；可通过 `QWENPAW_WORKING_DIR` 环境变量覆盖）
3. **默认值** — 回退到智能体 ID `"default"` 和工作区目录 `WORKING_DIR/workspaces/default/`
