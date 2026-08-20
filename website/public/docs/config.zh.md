# 配置与工作目录

QwenPaw 的所有配置和数据都存储在**工作目录**中。本页说明：

- **目录结构** — 文件都在哪里，各目录的作用
- **环境变量** — 如何用环境变量自定义路径和行为
- **配置文件** — `config.json` 和 `agent.json` 的完整字段说明

从 **v0.1.0** 开始，QwenPaw 支持**多智能体**，配置分为两层：

1. **全局配置**（`config.json`）— 模型提供商、智能体列表、全局设置
2. **智能体配置**（`agent.json`）— 每个智能体的独立配置（频道、心跳、工具等）

---

## 目录结构

默认工作目录是 `~/.qwenpaw`。运行 `qwenpaw init` 后的完整结构：

```
$QWENPAW_WORKING_DIR/                      # 默认 ~/.qwenpaw
├── config.json                          # 全局配置
├── workspaces/
│   ├── default/                         # 默认智能体工作区
│   │   ├── agent.json                   # 智能体配置
│   │   ├── chats.json                   # 对话历史
│   │   ├── jobs.json                    # 定时任务
│   │   ├── token_usage.json             # Token 消耗记录
│   │   ├── AGENTS.md                    # 人设文件
│   │   ├── SOUL.md                      # 人设文件
│   │   ├── PROFILE.md                   # 人设文件
│   │   ├── BOOTSTRAP.md                 # 首次引导文件（完成后自动删除）
│   │   ├── MEMORY.md                    # 长期记忆
│   │   ├── skills/                      # 本地技能目录
│   │   ├── skill.json                   # 技能启用状态与配置
│   │   ├── memory/                      # 每日记忆文件
│   │   ├── .browser-profile/            # 浏览器持久化 profile（统一浏览器）
│   │   └── browser/                     # 浏览器数据（旧版兼容模式）
│   └── abc123/                          # 其他智能体工作区
│       └── ...
└── skill_pool/                          # 本地共享技能池
    ├── skill.json                       # 池元数据
    └── ...

$QWENPAW_SECRET_DIR/                       # 默认 ~/.qwenpaw.secret
├── providers.json                       # 模型提供商配置与 API Key
└── envs.json                            # 环境变量
```

> **路径说明：** `$QWENPAW_WORKING_DIR` 和 `$QWENPAW_SECRET_DIR` 是环境变量，默认值分别为 `~/.qwenpaw` 和 `~/.qwenpaw.secret`。可通过环境变量自定义，详见下方"环境变量"章节。

---

## 环境变量

可通过环境变量自定义路径和行为：

**路径相关：**

| 变量                       | 默认值              | 说明                                                                                                                                                                                                                           |
| -------------------------- | ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `QWENPAW_WORKING_DIR`      | `~/.qwenpaw`        | 工作目录根路径                                                                                                                                                                                                                 |
| `QWENPAW_SECRET_DIR`       | `~/.qwenpaw.secret` | 敏感数据目录（存放 `providers.json` 和 `envs.json`）。Docker 中默认为 `/app/working.secret`                                                                                                                                    |
| `QWENPAW_KEYRING_ACCOUNT`  | _(自动)_            | 主密钥在操作系统钥匙串中的账户名。默认为 `master_key`；当设置了 `QWENPAW_WORKING_DIR`/`QWENPAW_SECRET_DIR`（例如开发检出）时会自动派生为每个安装独立的账户名，使开发安装不会覆盖稳定安装的密钥。可显式设置以命名某个配置档案。 |
| `QWENPAW_CONFIG_FILE`      | `config.json`       | 配置文件名（相对于 `QWENPAW_WORKING_DIR`）                                                                                                                                                                                     |
| `QWENPAW_HEARTBEAT_FILE`   | `HEARTBEAT.md`      | 心跳文件名（相对于智能体工作区）                                                                                                                                                                                               |
| `QWENPAW_JOBS_FILE`        | `jobs.json`         | 定时任务文件名（相对于智能体工作区）                                                                                                                                                                                           |
| `QWENPAW_CHATS_FILE`       | `chats.json`        | 对话历史文件名（相对于智能体工作区）                                                                                                                                                                                           |
| `QWENPAW_TOKEN_USAGE_FILE` | `token_usage.json`  | Token 消耗记录文件名（相对于智能体工作区）                                                                                                                                                                                     |

**其他配置：**

| 变量                                   | 默认值         | 说明                                                                                 |
| -------------------------------------- | -------------- | ------------------------------------------------------------------------------------ |
| `QWENPAW_LOG_LEVEL`                    | `info`         | 日志级别（`debug` / `info` / `warning` / `error` / `critical`）                      |
| `QWENPAW_LOG_MAX_SIZE`                 | `5MiB`         | 当前日志文件大小上限，支持字节数及 `10MB`、`1GiB` 等后缀                             |
| `QWENPAW_LOG_MAX_BACKUPS`              | `3`            | 保留的轮转日志份数；设为 `0` 时不保留备份                                            |
| `QWENPAW_MEMORY_COMPACT_THRESHOLD`     | `100000`       | 触发记忆压缩的字符阈值                                                               |
| `QWENPAW_MEMORY_COMPACT_KEEP_RECENT`   | `3`            | 压缩后保留的最近消息数                                                               |
| `QWENPAW_MEMORY_COMPACT_RATIO`         | `0.7`          | 触发压缩的阈值比例（相对于上下文窗口大小）                                           |
| `QWENPAW_REMOTE_IMAGE_DOWNLOAD_MAX_MB` | `50`           | `view_image` 远程图片下载上限（MiB）。接受任意正整数；非法值、`0` 或负数回退到默认值 |
| `QWENPAW_CONSOLE_STATIC_DIR`           | _（自动检测）_ | 控制台前端静态文件路径                                                               |

**安全与认证：**

| 变量                         | 默认值  | 说明                                     |
| ---------------------------- | ------- | ---------------------------------------- |
| `QWENPAW_AUTH_ENABLED`       | `false` | 是否启用 Web 控制台登录认证              |
| `QWENPAW_AUTH_USERNAME`      | -       | 自动注册时的管理员用户名（可选）         |
| `QWENPAW_AUTH_PASSWORD`      | -       | 自动注册时的管理员密码（可选）           |
| `QWENPAW_TOOL_GUARD_ENABLED` | `true`  | 是否启用工具守卫                         |
| `QWENPAW_SKILL_SCAN_MODE`    | `warn`  | 技能扫描模式（`block` / `warn` / `off`） |

---

## 配置文件结构

从 **v0.1.0** 开始，配置文件分为两层：

1. **全局配置** - `~/.qwenpaw/config.json`（提供商、环境变量、智能体列表）
2. **智能体配置** - `~/.qwenpaw/workspaces/{agent_id}/agent.json`（每个智能体的独立配置）

QwenPaw 会在单个服务进程内串行写入智能体配置，并拒绝基于旧磁盘快照的保存。原子文件替换可避免出现不完整 JSON。外部编辑器不参与该进程锁，因此在最终校验与替换之间发生的外部修改不属于严格一致性保证；收到 409 冲突后，请重新加载配置再重试。

### 全局 config.json

存放全局共享的配置：

```json
{
  "agents": {
    "active_agent": "default",
    "profiles": {
      "default": {
        "id": "default",
        "name": "默认智能体",
        "description": "默认工作区智能体",
        "enabled": true,
        "workspace_dir": "~/.qwenpaw/workspaces/default"
      }
    }
  },
  "last_api": {
    "host": "127.0.0.1",
    "port": 8088
  },
  "show_tool_details": true,
  "user_timezone": "Asia/Shanghai"
}
```

**全局 config.json 字段说明：**

| 字段                  | 类型           | 默认值         | 说明                                  |
| --------------------- | -------------- | -------------- | ------------------------------------- |
| `agents.active_agent` | string         | `"default"`    | 当前激活的智能体 ID                   |
| `agents.profiles`     | object         | `{}`           | 智能体配置引用字典（key 为 agent_id） |
| `last_api.host`       | string \| null | `null`         | 上次 `qwenpaw app` 启动的主机地址     |
| `last_api.port`       | int \| null    | `null`         | 上次 `qwenpaw app` 启动的端口         |
| `show_tool_details`   | bool           | `true`         | 是否在频道消息中显示工具调用/返回详情 |
| `user_timezone`       | string         | _（系统时区）_ | IANA 时区名称（如 `"Asia/Shanghai"`） |

**`agents.profiles[agent_id]`** 引用字段：

| 字段            | 类型   | 必填 | 说明                                                              |
| --------------- | ------ | ---- | ----------------------------------------------------------------- |
| `id`            | string | 是   | 智能体唯一标识                                                    |
| `name`          | string | 是   | 智能体显示名称                                                    |
| `description`   | string | 否   | 智能体描述（用于多智能体协作时的分工判断）                        |
| `enabled`       | bool   | 是   | 是否启用该智能体                                                  |
| `workspace_dir` | string | 否   | 工作区路径（可选，默认为 `$QWENPAW_WORKING_DIR/workspaces/{id}`） |

> **向后兼容：** 全局 config.json 中还保留了 `channels`、`mcp`、`tools`、`security` 等字段，用于向后兼容旧版本。在多智能体模式下，这些配置应该在各智能体的 `agent.json` 中设置。
>
> **配置优先级：** 智能体的 `agent.json` 优先级高于全局 `config.json`。如果两处都配置了相同字段，系统会使用 `agent.json` 中的值。建议在多智能体模式下，将所有配置都写在各智能体的 `agent.json` 中。

> **模型提供商配置** 存储在 `$QWENPAW_SECRET_DIR/providers.json`（默认 `~/.qwenpaw.secret/providers.json`）。
> **环境变量配置** 存储在 `$QWENPAW_SECRET_DIR/envs.json`（默认 `~/.qwenpaw.secret/envs.json`）。

### 智能体配置 agent.json

每个智能体在其工作区目录（`$QWENPAW_WORKING_DIR/workspaces/{agent_id}/`）下有独立的 `agent.json`，用于存储该智能体的所有配置（频道、工具、心跳、MCP、安全等）。这样不同智能体可以有完全不同的配置，互不干扰。

```json
{
  "id": "default",
  "name": "默认智能体",
  "description": "默认工作区智能体",
  "workspace_dir": "",
  "channels": {
    "console": {
      "enabled": true,
      "bot_prefix": ""
    },
    "dingtalk": {
      "enabled": false,
      "bot_prefix": "",
      "client_id": "",
      "client_secret": ""
    }
  },
  "mcp": {
    "clients": {
      "filesystem": {
        "name": "文件系统访问",
        "enabled": true,
        "command": "npx",
        "args": [
          "-y",
          "@modelcontextprotocol/server-filesystem",
          "/path/to/folder"
        ]
      }
    }
  },
  "heartbeat": {
    "enabled": false,
    "every": "30m",
    "target": "main",
    "timeoutSeconds": 300,
    "activeHours": null
  },
  "running": {
    "max_iters": 50,
    "llm_retry_enabled": true,
    "llm_max_retries": 3,
    "llm_backoff_base": 1.0,
    "llm_backoff_cap": 10.0,
    "max_input_length": 131072
  },
  "active_model": null,
  "language": "zh",
  "system_prompt_files": ["AGENTS.md", "SOUL.md", "PROFILE.md"],
  "tools": {
    "builtin_tools": {}
  },
  "security": {
    "tool_guard": {
      "enabled": true,
      "shell_evasion_checks": {
        "command_substitution": false,
        "obfuscated_flags": false,
        "backslash_escaped_whitespace": false,
        "backslash_escaped_operators": false,
        "newlines": false,
        "comment_quote_desync": false,
        "quoted_newline": false
      }
    },
    "file_guard": {
      "enabled": true
    },
    "skill_scanner": {
      "mode": "warn"
    },
    "allow_no_auth_hosts": ["127.0.0.1", "::1"]
  }
}
```

> **说明：** 完整的字段列表和说明见下方各小节。智能体配置可以在控制台中管理，也可以直接编辑 `agent.json` 文件。

---

### agent.json 字段详解

#### `channels` — 消息频道配置

每个频道都有通用字段（如 `enabled`、`bot_prefix`、访问控制策略等）和频道专属字段（如钉钉的 `client_id`、`client_secret`）。

**支持的频道：**

- **console** — 控制台（默认启用）
- **dingtalk** — 钉钉
- **feishu** — 飞书/Lark
- **discord** — Discord
- **telegram** — Telegram
- **qq** — QQ 机器人
- **imessage** — iMessage（仅 macOS）
- **mattermost** — Mattermost
- **matrix** — Matrix
- **wecom** — 企业微信
- **wechat** — 微信个人（iLink）
- **xiaoyi** — 华为小艺
- **mqtt** — MQTT
- **voice** — Voice

> **完整配置说明：** 每个频道的通用字段、专属字段（如钉钉的 `client_id`、飞书的 `app_id`）和详细配置步骤请参见 [频道配置](./channels)。

管理方式：控制台（智能体 → 频道）或直接编辑 `agent.json`。

> **热加载：** 系统每 2 秒自动检测 `agent.json` 变化，修改频道配置后会自动重载，无需重启。

---

#### `mcp` — MCP 客户端配置

MCP（模型上下文协议）允许智能体连接外部服务（如 Filesystem、Git、SQLite 等 MCP 服务器）。

每个 MCP 客户端包含名称、启用状态、传输方式（stdio/HTTP/SSE）、启动命令或 URL 等字段。

> **完整配置说明：** MCP 客户端的完整字段说明、配置格式、示例和使用方式请参见 [MCP](./mcp)。

管理方式：控制台（智能体 → MCP）或直接编辑 `agent.json`。

---

#### `heartbeat` — 心跳配置

心跳是定时自检功能，按固定间隔执行 `HEARTBEAT.md` 中的任务。

| 字段             | 类型           | 默认值   | 说明                                                                         |
| ---------------- | -------------- | -------- | ---------------------------------------------------------------------------- |
| `enabled`        | bool           | `false`  | 是否启用心跳功能                                                             |
| `every`          | string         | `"30m"`  | 运行间隔。支持 `Nh`、`Nm`、`Ns` 组合，如 `"1h"`、`"30m"`、`"2h30m"`、`"90s"` |
| `target`         | string         | `"main"` | `"main"` = 只在主会话运行；`"last"` = 把结果发到最后一个发消息的频道/用户    |
| `timeoutSeconds` | int            | `300`    | 单次心跳执行的最长时间，单位秒。有效范围：`1`–`3600`                         |
| `activeHours`    | object \| null | `null`   | 可选活跃时段（`start`、`end` 时间，24 小时制）                               |

详细说明请看 [心跳](./heartbeat)。

---

#### `running` — 运行时配置

控制智能体的运行行为、重试策略、上下文管理和记忆配置。

**基础运行参数：**

| 字段                         | 类型  | 默认值  | 说明                                                                                                                                                                                                                     |
| ---------------------------- | ----- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `max_iters`                  | int   | `100`   | ReAct Agent 推理-执行循环的最大轮数（必须 ≥ 1）                                                                                                                                                                          |
| `shell_command_timeout`      | float | `60.0`  | `execute_shell_command` 的默认超时时间（秒）。LLM 可在每次调用时通过 timeout 参数覆盖此值                                                                                                                                |
| `shell_command_executable`   | str   | `""`    | `execute_shell_command` 在 Linux/macOS 上使用的 shell 路径（如 `/bin/bash`、`/bin/zsh`）。Windows 上支持 `powershell.exe` / `pwsh.exe`。留空时依次回退到 `$SHELL` 环境变量，再回退到 `/bin/sh`（Windows 上为 `cmd.exe`） |
| `auto_continue_on_text_only` | bool  | `false` | 启用后,若模型只返回文本而未调用工具,Agent 会自动重试最多两轮推理                                                                                                                                                         |

**LLM 重试与限流：**

| 字段                    | 类型  | 默认值  | 说明                                                        |
| ----------------------- | ----- | ------- | ----------------------------------------------------------- |
| `llm_retry_enabled`     | bool  | `true`  | 是否对限流、超时、连接中断等瞬时 LLM API 错误自动重试       |
| `llm_max_retries`       | int   | `3`     | 瞬时 LLM API 错误的最大重试次数（必须 ≥ 1）                 |
| `llm_backoff_base`      | float | `1.0`   | 指数退避的基础等待时间（秒，必须 ≥ 0.1）                    |
| `llm_backoff_cap`       | float | `10.0`  | 退避等待时间上限（秒，必须 ≥ 0.5，且 ≥ `llm_backoff_base`） |
| `llm_max_concurrent`    | int   | `10`    | 最大并发 LLM 调用数（跨所有智能体共享）                     |
| `llm_max_qpm`           | int   | `600`   | 每分钟最大请求数限制（QPM）。0 = 不限制                     |
| `llm_rate_limit_pause`  | float | `5.0`   | 收到 429 限流响应时的全局暂停时间（秒）                     |
| `llm_rate_limit_jitter` | float | `1.0`   | 限流暂停的随机抖动范围（秒），避免并发请求同时恢复          |
| `llm_acquire_timeout`   | float | `300.0` | 等待获取限流槽的最大超时时间（秒）                          |

**上下文管理：**

| 字段                       | 类型   | 默认值          | 说明                                                  |
| -------------------------- | ------ | --------------- | ----------------------------------------------------- |
| `max_input_length`         | int    | `131072` (128K) | 模型上下文窗口的最大输入长度（token 数，必须 ≥ 1000） |
| `history_max_length`       | int    | `10000`         | `/history` 命令输出的最大长度（字符数）               |
| `context_manager_backend`  | string | `"light"`       | 上下文管理器后端类型                                  |
| `memory_manager_backend`   | string | `"remelight"`   | 记忆管理器后端类型                                    |
| `light_context_config`     | object | _（见下方）_    | Light 上下文管理器配置                                |
| `reme_light_memory_config` | object | _（见下方）_    | ReMeLight 记忆管理器配置                              |

**Light 上下文配置（`light_context_config` 对象）：**

| 字段                           | 类型   | 默认值     | 说明                                            |
| ------------------------------ | ------ | ---------- | ----------------------------------------------- |
| `dialog_path`                  | string | `"dialog"` | 对话持久化目录（相对于工作目录）                |
| `token_count_estimate_divisor` | float  | `4.0`      | 基于字节的 token 估算除数（byte_len / divisor） |

**Light 上下文压缩配置（`light_context_config.context_compact_config` 对象）：**

| 字段                      | 类型  | 默认值 | 说明                                            |
| ------------------------- | ----- | ------ | ----------------------------------------------- |
| `enabled`                 | bool  | `true` | 是否启用自动上下文压缩                          |
| `compact_threshold_ratio` | float | `0.8`  | 触发压缩的阈值比例（相对于 `max_input_length`） |
| `reserve_threshold_ratio` | float | `0.1`  | 压缩时保留的最近上下文比例                      |

**Light 工具结果修剪配置（`light_context_config.tool_result_pruning_config` 对象）：**

| 字段                           | 类型 | 默认值  | 说明                                                                |
| ------------------------------ | ---- | ------- | ------------------------------------------------------------------- |
| `enabled`                      | bool | `true`  | 是否启用工具结果修剪                                                |
| `pruning_recent_n`             | int  | `2`     | scroll compact 前，最近 N 条包含工具结果的消息使用最近预览阈值      |
| `pruning_old_msg_max_bytes`    | int  | `3000`  | scroll compact 后仍保留在 live context 中的工具结果轻量预览字节阈值 |
| `pruning_recent_msg_max_bytes` | int  | `50000` | 工具结果进入 context 前及仍属于 recent 时使用的预览字节阈值         |
| `offload_retention_days`       | int  | `5`     | 工具结果文件保留天数                                                |

**ReMeLight 记忆配置（`reme_light_memory_config` 对象）：**

| 字段                             | 类型        | 默认值           | 说明                                                                                              |
| -------------------------------- | ----------- | ---------------- | ------------------------------------------------------------------------------------------------- |
| `metadata_dir`                   | string      | `"mem_metadata"` | ReMe 持久状态子目录                                                                               |
| `session_dir`                    | string      | `"mem_session"`  | ReMe auto-memory 使用的来源对话日志子目录                                                         |
| `mem_session_dir`                | string      | `"mem_agent"`    | ReMe 内部 memory-agent 会话子目录                                                                 |
| `resource_dir`                   | string      | `"resource"`     | Daily Paper 与未来知识工作流使用的原始资源目录                                                    |
| `daily_dir`                      | string      | `"memory"`       | 每日记忆子目录                                                                                    |
| `digest_dir`                     | string      | `"digest"`       | digest 记忆子目录                                                                                 |
| `auto_memory_inbox_push_enabled` | bool        | `true`           | 是否在 Auto-Memory 实际改变记忆或执行失败时推送到收件箱                                           |
| `auto_dream_inbox_push_enabled`  | bool        | `true`           | 是否在 Auto-Dream 实际改变记忆或执行失败时推送到收件箱                                            |
| `daily_paper_inbox_push_enabled` | bool        | `true`           | 是否将 Daily Paper 结果推送到收件箱                                                               |
| `auto_memory_interval`           | int \| null | `5`              | 每隔 N 次用户查询触发自动记忆。`None` 或 `<= 0` 表示禁用周期自动记忆                              |
| `dream_cron_enabled`             | bool        | `true`           | 是否启用按 Cron 定时执行的梦境记忆优化任务                                                        |
| `dream_cron`                     | string      | `"0 23 * * *"`   | 梦境记忆优化任务的有效 5 段 Cron 表达式（启用时必填）；触发后随机延迟 0–60 秒启动，以避免集中调用 |
| `daily_paper_cron_enabled`       | bool        | `false`          | 是否启用按 Cron 定时执行的每日论文任务                                                            |
| `daily_paper_cron`               | string      | `"0 9 * * *"`    | 每日论文任务的有效 5 段 Cron 表达式（启用时必填）                                                 |
| `daily_paper_use_hf_mirror`      | bool        | `false`          | 是否通过 Hugging Face 镜像站获取每日论文信息                                                      |
| `daily_paper_topics`             | string      | `""`             | 每日论文筛选时优先关注的主题                                                                      |
| `memory_search_enabled`          | bool        | `true`           | 是否向智能体提供 `memory_search` 工具；不影响自动记忆搜索                                         |
| `auto_memory_search_config`      | object      | _（见下方）_     | 自动记忆搜索配置                                                                                  |
| `embedding_model_config`         | object      | _（见下方）_     | Embedding 模型配置                                                                                |
| `needs_reindex`                  | bool        | `false`          | 运行时维护的标记，表示已保存的向量空间发生变化，需要手动重建索引                                  |

> `rebuild_memory_index_on_start` 已不再支持。仅在确有需要时通过控制台或维护 API 重建索引，详见
> [重建记忆搜索索引](./memory#重建索引)。

已弃用的 `inbox_push_enabled` 仅用于迁移：它会初始化尚未设置的各任务 Inbox 开关，随后从序列化配置中排除。

**自动记忆搜索配置（`reme_light_memory_config.auto_memory_search_config` 对象）：**

| 字段          | 类型 | 默认值  | 说明                             |
| ------------- | ---- | ------- | -------------------------------- |
| `enabled`     | bool | `false` | 是否在每轮对话时自动执行记忆搜索 |
| `max_results` | int  | `2`     | 自动搜索时最多返回的结果数       |

**Embedding 配置（`reme_light_memory_config.embedding_model_config` 对象）：**

| 字段               | 类型   | 默认值     | 说明                                                                                  |
| ------------------ | ------ | ---------- | ------------------------------------------------------------------------------------- |
| `backend`          | string | `"openai"` | Embedding 后端类型：`openai`、`dashscope`、`dashscope_multimodal`、`gemini`、`ollama` |
| `api_key`          | string | `""`       | Embedding 提供商的 API Key。OpenAI 兼容和 Gemini 后端必填                             |
| `base_url`         | string | `""`       | OpenAI 兼容后端的可选自定义 API 地址；Ollama 后端会作为 host 传递                     |
| `model_name`       | string | `""`       | Embedding 模型名称（如 `"text-embedding-3-small"`）                                   |
| `dimensions`       | int    | `1024`     | 预期的 Embedding 向量维度，用于返回值校验、索引和缓存                                 |
| `enable_cache`     | bool   | `true`     | 是否启用 Embedding 缓存                                                               |
| `use_dimensions`   | bool   | `false`    | OpenAI 后端是否在 API 请求中传递 `dimensions` 参数                                    |
| `max_cache_size`   | int    | `10000`    | 最大缓存大小                                                                          |
| `max_input_length` | int    | `8192`     | 单条 Embedding 输入的近似字符预算，并非精确的 Token 上限                              |
| `max_batch_size`   | int    | `10`       | 批处理的最大批量大小                                                                  |

`use_dimensions` 仅控制 OpenAI 兼容请求中是否携带 `dimensions` 参数。关闭后，`dimensions`
仍用于校验服务返回的向量长度以及配置索引和缓存，因此必须填写模型实际输出的维度。部分 vLLM
等 OpenAI 兼容服务不支持该请求参数，此时应关闭 `use_dimensions`。

每条 Embedding 文本会在请求前按照 `max_input_length` 分别截断。该值按字符近似计算，中文、CJK
及其他全角字符会使用更保守的权重并预留安全余量，不会调用模型 tokenizer 计算精确 Token 数。

向量检索只有在当前后端具备最低可运行配置时才会启用；这些条件与 AgentScope credential 要求保持一致：

| 后端                                            | 启用条件                         | Credential 映射                |
| ----------------------------------------------- | -------------------------------- | ------------------------------ |
| `openai` / `dashscope` / `dashscope_multimodal` | `model_name` 和 `api_key` 均非空 | `api_key`；可选 `base_url`     |
| `gemini`                                        | `model_name` 和 `api_key` 均非空 | `api_key`                      |
| `ollama`                                        | `model_name` 非空                | 可选 `host`（来自 `base_url`） |

不满足启用条件时，ReMe 仍会保留关键词索引和 wikilink 图谱索引，但不会启用 embedding 向量索引。

这些配置也可以在控制台的 **智能体 → 运行配置** 页面中修改。自动记忆间隔、自动搜索条数等按需读取的字段，
保存后会作用于后续回合。Embedding 保存采用事务式流程：QwenPaw 先持久化提交的运行配置，再尝试应用到
当前 ReMe runtime。若当前服务指纹已经成功测试，可以原位替换运行中的 Embedding 模型；否则会重新创建内嵌 ReMe。
若两种方式都失败，系统会在不覆盖并发修改的前提下回滚本次字段并返回错误。保存后始终会调度正常的 Agent 自动重载，
无需手动重启。索引正在重建时修改 Embedding 会返回 HTTP `409`。

修改 `backend`、规范化后的 `base_url`、`model_name`、`dimensions` 或 `use_dimensions` 会设置
`needs_reindex=true`；只修改 API Key 或缓存、批量限制不会。向量空间热更新会清空 Embedding 缓存，
但**不会**自动重建已有文件向量，仍需在 Console 或维护 API 中显式执行重建。只有针对当前向量空间成功完成的重建
才会清除 `needs_reindex`。

控制台中的 Embedding“已开启/未开启”状态会根据当前未保存表单实时计算，只表示 Backend、模型名称和必要凭证是否满足上述启用条件，
不表示服务已经连通或配置已经应用到运行中的 Agent。“已验证”表示真实测试请求成功；只有保存配置后，变更才会应用到运行状态。

---

#### `language` & `system_prompt_files` — 人设文件配置

| 字段                  | 类型          | 默认值                                   | 说明                             |
| --------------------- | ------------- | ---------------------------------------- | -------------------------------- |
| `language`            | string        | `"zh"`                                   | 智能体语言（`zh` / `en` / `ru`） |
| `system_prompt_files` | array[string] | `["AGENTS.md", "SOUL.md", "PROFILE.md"]` | 加载到系统提示词的人设文件列表   |

**人设文件** 定义智能体的行为和个性，存放在工作区目录下。你可以：

- 在控制台的 **智能体 → 工作区** 页面管理人设文件（编辑、启用/禁用、调整顺序）
- 直接编辑 `system_prompt_files` 数组来控制加载哪些文件
- 在控制台的 **智能体 → 运行配置** 页面切换语言（会覆盖现有人设文件）

**详细说明：** 参见 [智能体人设](./persona) 文档。

---

#### `active_model` — 当前使用的模型

指定该智能体使用的模型。

| 字段          | 类型   | 默认值 | 说明                                          |
| ------------- | ------ | ------ | --------------------------------------------- |
| `provider_id` | string | `""`   | 模型提供商 ID（如 `"dashscope"`、`"openai"`） |
| `model`       | string | `""`   | 模型名称（如 `"qwen-max"`、`"gpt-4"`）        |

为 `null` 时使用全局默认模型。可在控制台（智能体 → 模型设置）中配置。

---

#### `approval_level` — 工具执行安全级别

| 字段             | 类型   | 默认值   | 说明                                                                          |
| ---------------- | ------ | -------- | ----------------------------------------------------------------------------- |
| `approval_level` | string | `"AUTO"` | 工具执行安全级别: `STRICT`、`SMART`、`AUTO`、`OFF`。详见 [安全](./security)。 |

---

#### `tools` — 工具配置

控制智能体可用的内置工具。每个工具可以单独启用/禁用，配置是否显示给用户，以及是否异步执行。

> **完整配置说明：** 工具的详细字段结构、配置示例等请参见 [MCP 与内置工具](./mcp)。

管理方式：控制台（智能体 → 工具配置）或直接编辑 `agent.json`。

---

#### `security` — 安全配置

包含三个防护模块：

- **`tool_guard`** — 工具守卫（运行时检测危险命令和注入攻击）
- **`file_guard`** — 文件守卫（保护敏感文件访问）
- **`skill_scanner`** — 技能扫描器（技能启用前扫描恶意代码）

顶层字段：

| 字段                  | 类型     | 默认值                 | 说明                                                  |
| --------------------- | -------- | ---------------------- | ----------------------------------------------------- |
| `allow_no_auth_hosts` | string[] | `["127.0.0.1", "::1"]` | IP 白名单，绕过 Web 登录认证。默认允许 localhost 访问 |

> **完整配置说明：** 每个模块的详细字段说明、安全规则、自定义规则配置等请参见 [安全](./security)。

管理方式：控制台（设置 → 安全配置）或直接编辑 `agent.json`。

---

#### `state/last_dispatch.json` — 最近一次消息分发状态

记录最近用户消息来源，用于心跳 `target = "last"` 时的消息发送。
该运行状态位于智能体工作区，不属于 `agent.json` 配置。

| 字段         | 类型   | 默认值 | 说明                                     |
| ------------ | ------ | ------ | ---------------------------------------- |
| `channel`    | string | `""`   | 频道名称（如 `"discord"`、`"dingtalk"`） |
| `user_id`    | string | `""`   | 该频道中的用户 ID                        |
| `session_id` | string | `""`   | 会话/对话 ID                             |

系统以原子写方式自动更新，无需手动配置。

---

## 模型提供商

QwenPaw 需要 LLM 提供商才能运行。配置存储在 `$QWENPAW_SECRET_DIR/providers.json`（默认 `~/.qwenpaw.secret/providers.json`）。

有三种设置方式：

- **`qwenpaw init`** — 交互式向导，最简单
- **控制台 UI** — 在设置 → 模型页面配置
- **API** — `PUT /providers/{id}` 和 `PUT /providers/active_llm`

**内置提供商列表：**

| 提供商                                  | ID                       | 说明                          |
| --------------------------------------- | ------------------------ | ----------------------------- |
| QwenPaw Local                           | `qwenpaw-local`          | 本地 llama.cpp 后端           |
| Ollama                                  | `ollama`                 | 本地 Ollama 服务              |
| LM Studio                               | `lmstudio`               | 本地 LM Studio 服务           |
| OpenRouter                              | `openrouter`             | OpenRouter 模型聚合平台       |
| ModelScope（魔搭）                      | `modelscope`             | 魔搭社区模型服务              |
| DashScope（灵积）                       | `dashscope`              | 阿里云灵积模型服务            |
| 阿里云百炼 Coding Plan（China）         | `aliyun-codingplan`      | 阿里云百炼 Coding Plan        |
| 阿里云百炼 Coding Plan（International） | `aliyun-codingplan-intl` | 阿里云百炼 Coding Plan 国际版 |
| OpenAI                                  | `openai`                 | OpenAI API                    |
| Azure OpenAI                            | `azure-openai`           | Azure OpenAI Service          |
| Anthropic                               | `anthropic`              | Anthropic Claude API          |
| Google Gemini                           | `gemini`                 | Google Gemini API             |
| DeepSeek                                | `deepseek`               | DeepSeek API                  |
| Kimi（China）                           | `kimi-cn`                | Moonshot Kimi 国内版          |
| Kimi（International）                   | `kimi-intl`              | Moonshot Kimi 国际版          |
| MiniMax（China）                        | `minimax-cn`             | MiniMax 国内版                |
| MiniMax（International）                | `minimax`                | MiniMax 国际版                |
| Zhipu（BigModel）                       | `zhipu-cn`               | 智谱国内版标准 API            |
| Zhipu Coding Plan（BigModel）           | `zhipu-cn-codingplan`    | 智谱国内版 Coding Plan        |
| Zhipu（Z.AI）                           | `zhipu-intl`             | 智谱国际版标准 API            |
| Zhipu Coding Plan（Z.AI）               | `zhipu-intl-codingplan`  | 智谱国际版 Coding Plan        |
| OpenCode                                | `opencode`               | OpenCode Zen 模型服务         |
| SiliconFlow（China）                    | `siliconflow-cn`         | 硅基流动国内版                |
| SiliconFlow（International）            | `siliconflow-intl`       | 硅基流动国际版                |
| 自定义                                  | `custom`                 | 自定义 OpenAI 兼容服务        |

> **完整配置说明：** 每个提供商的详细配置方式、`providers.json` 字段结构、模型发现等请参见 [模型](./models)。

> **提示：** 运行 `qwenpaw init` 跟着提示走就行——它会列出每个提供商的可用模型让你直接选。

---

## 工具环境变量

部分工具和 MCP 服务需要额外的 API Key（如网络搜索用的 `TAVILY_API_KEY`）。有三种管理方式：

- **`qwenpaw init`** — 初始化时会问 "Configure environment variables?"
- **控制台 UI** — 在设置页面编辑
- **API** — `GET/PUT/DELETE /envs`

设置好的变量会在应用启动时自动加载，所有工具和子进程都可以通过 `os.environ` 读取。

> **注意：** 环境变量的值（如第三方 API Key）的有效性需要用户自行保证。QwenPaw 只负责存储和注入，不会校验其正确性。

---

## 浏览器

浏览器配置写在全局 `~/.qwenpaw/config.json` 的 `browser` 段，对所有智能体生效：

```json
{
  "browser": {
    "experimental": true,
    "backend": "auto",
    "identity": "auto",
    "headless": "auto"
  }
}
```

常用字段：

| 字段           | 类型   | 默认值   | 说明                                                                    |
| -------------- | ------ | -------- | ----------------------------------------------------------------------- |
| `experimental` | bool   | `true`   | 是否使用新版统一浏览器；`false` 切回旧版实现。**改动需重启服务**        |
| `backend`      | string | `"auto"` | 独立浏览器的获取方式：`auto` / `launch` / `managed_cdp` / `connect_cdp` |
| `identity`     | string | `"auto"` | 浏览器身份：`auto` / `user` / `avatar` / `guest`                        |
| `headless`     | string | `"auto"` | `auto` 表示容器内或无图形界面时无头运行；也可写 `"true"` / `"false"`    |

浏览器数据按智能体工作区隔离，存放在 `workspaces/{agent_id}/.browser-profile/`（`managed_cdp` 用 `.browser-cdp/`，旧版兼容模式用 `browser/`）。`user` 身份使用你自己 Chrome 的 profile，不落这些目录。

> **完整配置说明：** 启动参数、视口、代理、空闲回收等全部字段，以及浏览器身份与接入方式的选择，请参见 [浏览器](./browser)。接入自己的 Chrome 需要安装 [Chrome 浏览器扩展](./chrome)。

---

## 技能（Skills）

技能通过两级目录管理：

- **`$QWENPAW_WORKING_DIR/skill_pool/`** — 本地共享技能池
- **`$QWENPAW_WORKING_DIR/workspaces/{agent_id}/skills/`** — 智能体工作区中的本地技能

每个技能是一个包含 `SKILL.md` 文件的子目录。技能的启用状态和配置存储在 `skill.json` 文件中（如 `~/.qwenpaw/workspaces/default/skill.json`）。

> **完整配置说明：** `skill.json` 的详细字段结构、技能池管理、广播、上传、Config 运行时注入等请参见 [技能](./skills)。

管理方式：

- **控制台**（智能体 → 技能）— 可视化管理、导入、启用/禁用
- **`qwenpaw skills config`** — CLI 交互式切换
- **直接编辑** `skill.json` — 手动添加或修改技能

---

## 记忆（Memory）

记忆系统为智能体提供长期记忆和每日记忆，存储在智能体工作区：

- **`MEMORY.md`** — 长期记忆（重要信息、用户偏好、项目上下文）
- **`memory/YYYY-MM-DD.md`** — 每日记忆（当天对话的关键信息）

记忆的写入和读取由智能体自动完成，用户通常无需手动干预。

> **完整配置说明：** Embedding 配置、全文检索配置、记忆压缩参数等请参见 [记忆](./memory)。

---

## 小结

- 默认一切都在 **`$QWENPAW_WORKING_DIR`**（默认 `~/.qwenpaw`）；可通过环境变量自定义。
- 从 **v0.1.0** 开始，配置分为两层：
  - **全局配置**（`config.json`）— 模型提供商、智能体列表、全局设置
  - **智能体配置**（`workspaces/{agent_id}/agent.json`）— 每个智能体的独立配置
- 主要通过 **控制台** 管理配置，也可直接编辑 JSON 文件。
- 智能体的人设由工作区中的 Markdown 文件定义，详见 [智能体人设](./persona)。
- 配置修改会**自动热加载**（每 2 秒检测一次），不需要重启。

---

## 相关页面

- [项目介绍](./intro) — 这个项目可以做什么
- [智能体人设](./persona) — 人设文件的详细说明和管理
- [频道配置](./channels) — 如何配置各个消息频道
- [心跳](./heartbeat) — 定时自检配置
- [多智能体](./multi-agent) — 多智能体配置、管理与协作
- [记忆](./memory) — 记忆系统详解
- [技能](./skills) — 技能系统详解
- [MCP](./mcp) — MCP 客户端配置
