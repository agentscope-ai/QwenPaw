# CLI

`copaw` 是 CoPaw 的命令行工具。本页按「上手 → 配置 → 日常管理」的顺序组织——
新用户从头读，老用户直接跳到需要的章节。

> 还不清楚「频道」「心跳」「定时任务」是什么？先看 [项目介绍](./intro)。

---

## 快速上手

第一次用 CoPaw，只需要这两条命令。

### copaw init

首次初始化，交互式引导你完成所有配置。

```bash
copaw init              # 交互式初始化（推荐新用户）
copaw init --defaults   # 不交互，用默认值（适合脚本）
copaw init --force      # 覆盖已有配置文件
```

**交互流程（按顺序）：**

1. **心跳** —— 间隔（如 `30m`）、目标（`main` / `last`）、可选活跃时间段。
2. **工具详情** —— 是否在频道消息中显示工具调用细节。
3. **语言** —— Agent 人设文件（SOUL.md 等）使用 `zh` / `en` / `ru`。
4. **频道** —— 可选配置 iMessage / Discord / DingTalk / Feishu / QQ / Console。
5. **LLM 提供商** —— 选择提供商、输入 API Key、选择模型（**必选**）。
6. **技能** —— 全部启用 / 不启用 / 自定义选择。
7. **环境变量** —— 可选添加工具所需的键值对。
8. **HEARTBEAT.md** —— 在默认编辑器中编辑心跳检查清单。

### copaw app

启动 CoPaw 服务。频道、定时任务、控制台等所有运行时功能都依赖此服务。

```bash
copaw app                             # 默认 127.0.0.1:8088
copaw app --host 0.0.0.0 --port 9090 # 自定义地址
copaw app --reload                    # 代码改动自动重载（开发用）
copaw app --log-level debug           # 详细日志
```

| 选项          | 默认值      | 说明                                                          |
| ------------- | ----------- | ------------------------------------------------------------- |
| `--host`      | `127.0.0.1` | 绑定地址                                                      |
| `--port`      | `8088`      | 绑定端口                                                      |
| `--reload`    | 关闭        | 文件变动时自动重载（仅开发用）                                |
| `--log-level` | `info`      | `critical` / `error` / `warning` / `info` / `debug` / `trace` |
| `--workers`   | —           | **[已废弃]** 将被忽略，CoPaw 始终使用 1 个 worker             |

> **说明：** `--workers` 选项因稳定性原因已废弃。CoPaw 被设计为单 worker 进程运行。多 worker 模式会导致内存状态管理和 WebSocket 连接出现问题。此选项将在未来版本中移除。

### 控制台

`copaw app` 启动后，在浏览器打开 `http://127.0.0.1:8088/` 即可进入 **控制台** ——
一个用于对话、频道、定时任务、技能、模型等的 Web 管理界面。详见 [控制台](./console)。

若未构建前端，根路径会返回类似 `{"message": "CoPaw Web Console is not available."}` 的提示信息（实际文案可能调整），API 仍可正常使用。

**构建方式：** 在项目 `console/` 目录下执行 `npm ci && npm run build`，
然后将构建产物复制到包目录：
`mkdir -p src/copaw/console && cp -R console/dist/. src/copaw/console/`。
Docker 镜像或 pip 安装包已内置控制台，无需单独构建。

### copaw daemon

查看运行状态、版本、最近日志等，无需启动对话。与在对话中发送 `/daemon status` 等效果一致（CLI 无进程时可查看本地信息）。

| 命令                         | 说明                                                                           |
| ---------------------------- | ------------------------------------------------------------------------------ |
| `copaw daemon status`        | 状态（配置、工作目录、记忆服务）                                               |
| `copaw daemon restart`       | 打印说明（在对话中用 /daemon restart 可进程内重载）                            |
| `copaw daemon reload-config` | 重新读取并校验配置（频道/MCP 变更需在对话中 /daemon restart 或重启进程后生效） |
| `copaw daemon version`       | 版本与路径                                                                     |
| `copaw daemon logs [-n N]`   | 最近 N 行日志（默认 100，来自工作目录 `copaw.log`）                            |

**多智能体支持：** 所有命令都支持 `--agent-id` 参数（默认为 `default`）。

```bash
copaw daemon status                     # 默认智能体状态
copaw daemon status --agent-id abc123   # 特定智能体状态
copaw daemon version
copaw daemon logs -n 50
```

---

## 模型与环境变量

使用 CoPaw 前至少需要配置一个 LLM 提供商。环境变量为内置工具（如网页搜索）提供凭据。

### copaw models

管理 LLM 提供商和活跃模型。

| 命令                                   | 说明                                   |
| -------------------------------------- | -------------------------------------- |
| `copaw models list`                    | 查看所有提供商、API Key 状态和当前模型 |
| `copaw models config`                  | 完整交互式配置：API Key → 选择模型     |
| `copaw models config-key [provider]`   | 单独配置某个提供商的 API Key           |
| `copaw models set-llm`                 | 只切换活跃模型（不改 API Key）         |
| `copaw models download <repo_id>`      | 下载本地模型（llama.cpp / MLX）        |
| `copaw models local`                   | 查看已下载的本地模型                   |
| `copaw models remove-local <model_id>` | 删除已下载的本地模型                   |
| `copaw models ollama-pull <model>`     | 下载 Ollama 模型                       |
| `copaw models ollama-list`             | 查看 Ollama 模型                       |
| `copaw models ollama-remove <model>`   | 删除 Ollama 模型                       |

```bash
copaw models list                    # 看当前状态
copaw models config                  # 完整交互式配置
copaw models config-key modelscope   # 只配 ModelScope 的 API Key
copaw models config-key dashscope    # 只配 DashScope 的 API Key
copaw models config-key custom       # 配置自定义提供商（Base URL + Key）
copaw models set-llm                 # 只切换模型
```

#### 本地模型

CoPaw 也支持通过 llama.cpp 或 MLX 在本地运行模型——无需 API Key。
先安装后端：`pip install 'copaw[llamacpp]'` 或 `pip install 'copaw[mlx]'`。

```bash
# 下载模型（自动选择 Q4_K_M GGUF）
copaw models download Qwen/Qwen3-4B-GGUF

# 下载 MLX 模型
copaw models download Qwen/Qwen3-4B --backend mlx

# 从 ModelScope 下载
copaw models download Qwen/Qwen2-0.5B-Instruct-GGUF --source modelscope

# 查看已下载模型
copaw models local
copaw models local --backend mlx

# 删除已下载模型
copaw models remove-local <model_id>
copaw models remove-local <model_id> --yes   # 跳过确认
```

| 选项        | 简写 | 默认值        | 说明                                           |
| ----------- | ---- | ------------- | ---------------------------------------------- |
| `--backend` | `-b` | `llamacpp`    | 目标后端（`llamacpp` 或 `mlx`）                |
| `--source`  | `-s` | `huggingface` | 下载源（`huggingface` 或 `modelscope`）        |
| `--file`    | `-f` | _（自动）_    | 指定文件名。省略时自动选择（GGUF 优先 Q4_K_M） |

#### Ollama 模型

CoPaw 集成 Ollama 以在本地运行模型。模型从 Ollama 守护进程动态加载——请先从 [ollama.com](https://ollama.com) 安装 Ollama。

安装 Ollama SDK：`pip install 'copaw[ollama]'`（或使用 `--extras ollama` 重新运行安装脚本）

```bash
# 下载 Ollama 模型
copaw models ollama-pull mistral:7b
copaw models ollama-pull qwen2.5:3b

# 查看 Ollama 模型
copaw models ollama-list

# 删除 Ollama 模型
copaw models ollama-remove mistral:7b
copaw models ollama-remove qwen2.5:3b --yes   # 跳过确认

# 在配置流程中使用（自动检测 Ollama 模型）
copaw models config           # 选择 Ollama → 从模型列表中选择
copaw models set-llm          # 切换到其他 Ollama 模型
```

**与本地模型的主要区别：**

- 模型来自 Ollama 守护进程（不由 CoPaw 下载）
- 使用 `ollama-pull` / `ollama-remove` 而非 `download` / `remove-local`
- 通过 Ollama CLI 或 CoPaw 添加/删除模型时，模型列表自动更新

> **注意：** API Key 的有效性需要用户自行保证，CoPaw 不会验证。
> 详见 [配置 — 模型提供商](./config#模型提供商)。

### copaw env

管理工具和技能在运行时使用的环境变量。

| 命令                      | 说明                 |
| ------------------------- | -------------------- |
| `copaw env list`          | 列出所有已配置的变量 |
| `copaw env set KEY VALUE` | 设置或更新变量       |
| `copaw env delete KEY`    | 删除变量             |

```bash
copaw env list
copaw env set TAVILY_API_KEY "tvly-xxxxxxxx"
copaw env set GITHUB_TOKEN "ghp_xxxxxxxx"
copaw env delete TAVILY_API_KEY
```

> **注意：** CoPaw 只负责存储和加载，值的有效性需要用户自行保证。
> 详见 [配置 — 环境变量](./config#环境变量)。

---

## 频道

将 CoPaw 连接到消息平台。

### copaw channels

管理频道配置（iMessage / Discord / DingTalk / Feishu / QQ / Console 等）并向频道发送消息。
**说明**：交互式配置用 `config`（无 `configure` 子命令）；卸载自定义频道用 `remove`（无 `uninstall`）。

**别名：** 可以用 `copaw channel`（单数）作为 `copaw channels` 的简写。

| 命令                           | 说明                                                                            |
| ------------------------------ | ------------------------------------------------------------------------------- |
| `copaw channels list`          | 查看所有频道的状态（密钥脱敏）                                                  |
| `copaw channels send`          | 向用户/会话单向发送消息（需要全部 5 个参数）                                    |
| `copaw channels install <key>` | 在 `custom_channels/` 安装频道：创建模板，或用 `--path` / `--url` 安装          |
| `copaw channels add <key>`     | 安装并加入 config；内置频道只写 config；支持 `--path` / `--url`                 |
| `copaw channels remove <key>`  | 从 `custom_channels/` 删除自定义频道（内置不可删）；`--keep-config` 保留 config |
| `copaw channels config`        | 交互式启用/禁用频道并填写凭据                                                   |

**多智能体支持：** 所有命令都支持 `--agent-id` 参数（默认为 `default`）。

```bash
copaw channels list                    # 看默认智能体的频道状态
copaw channels list --agent-id abc123  # 看特定智能体的频道状态
copaw channels install my_channel      # 创建自定义频道模板
copaw channels install my_channel --path ./my_channel.py
copaw channels add dingtalk            # 把钉钉加入 config
copaw channels remove my_channel       # 删除自定义频道（并默认从 config 移除）
copaw channels remove my_channel --keep-config   # 只删模块，保留 config 条目
copaw channels config                  # 交互式配置默认智能体
copaw channels config --agent-id abc123 # 交互式配置特定智能体
```

交互式 `config` 流程：依次选择频道、启用/禁用、填写凭据，循环直到选择「保存退出」。

| 频道         | 需要填写的字段                                                             |
| ------------ | -------------------------------------------------------------------------- |
| **iMessage** | Bot 前缀、数据库路径、轮询间隔                                             |
| **Discord**  | Bot 前缀、Bot Token、HTTP 代理、代理认证                                   |
| **DingTalk** | Bot 前缀、Client ID、Client Secret、消息类型、Card 模板 ID/Key、Robot Code |
| **Feishu**   | Bot 前缀、App ID、App Secret                                               |
| **QQ**       | Bot 前缀、App ID、Client Secret                                            |
| **Console**  | Bot 前缀                                                                   |

> 各平台凭据的获取步骤，请看 [频道配置](./channels)。

#### 向频道发送消息（主动通知）

> 对应技能：**Channel Message（频道消息推送）**

使用 `copaw channels send` 主动向用户/会话推送消息，支持所有已配置的频道。这是**单向发送** —— 不会返回回复。

智能体通过启用 **channel_message** 技能，可以在需要时自动使用此命令向用户发送主动通知。

**典型使用场景：**

- 任务完成后主动通知用户
- 定时提醒、告警、状态更新
- 将异步处理结果推送回原会话
- 用户明确要求"处理完后通知我"

```bash
# 第一步：查询可用会话
copaw chats list --agent-id my_bot --channel feishu

# 第二步：使用查询到的参数发送消息
copaw channels send \
  --agent-id my_bot \
  --channel feishu \
  --target-user ou_xxxx \
  --target-session session_id_xxxx \
  --text "任务已完成！"
```

**必填参数（全部 5 个）：**

- `--agent-id`：发送方智能体 ID
- `--channel`：目标频道（console/dingtalk/feishu/discord/imessage/qq）
- `--target-user`：用户 ID（从 `copaw chats list` 获取）
- `--target-session`：会话 ID（从 `copaw chats list` 获取）
- `--text`：消息内容

**重要提示：**

- 发送前必须先用 `copaw chats list` 查询 —— 不要猜测 `target-user` 或 `target-session`
- 如果有多个会话，优先使用最近更新的
- 这仅用于主动通知；智能体间通信请用 `copaw agents chat`（见下方"智能体"章节）

**与 `copaw agents chat` 的区别：**

- `copaw channels send`：智能体向用户/频道推送，单向，无回复
- `copaw agents chat`：智能体间通信，双向，有回复

---

## 智能体

管理智能体并支持智能体间通信。

### copaw agents

> 对应技能：**Multi-Agent Collaboration（多智能体协作）**

智能体通过启用 **multi_agent_collaboration** 技能，可以在需要时自动使用 `copaw agents chat` 与其他智能体协作。

**别名：** 可以用 `copaw agent`（单数）作为 `copaw agents` 的简写。

| 命令                | 说明                                             |
| ------------------- | ------------------------------------------------ |
| `copaw agents list` | 列出所有已配置的智能体（ID、名称、描述、工作区） |
| `copaw agents chat` | 与另一个智能体通信（双向，支持多轮对话）         |

```bash
# 列出所有智能体
copaw agents list
copaw agent list  # 单数别名效果相同

# 与另一个智能体对话（实时模式，单次）
copaw agents chat \
  --agent-id my_bot \
  --to-agent helper_bot \
  --text "请帮我分析这些数据"

# 多轮对话（session 复用）
copaw agents chat \
  --agent-id my_bot \
  --to-agent helper_bot \
  --session-id collab_session_001 \
  --text "继续上一个问题"

# 复杂任务（后台模式）
copaw agents chat --background \
  --agent-id my_bot \
  --to-agent data_analyst \
  --text "分析 /data/logs/2026-03-26.log 并生成详细报告"
# 返回 [TASK_ID: xxx] [SESSION: xxx]

# 查询后台任务状态（查询时 --to-agent 为可选）
copaw agents chat --background \
  --task-id <task_id>
# 状态流程：submitted → pending → running → finished
# finished 时结果显示：completed（✅）或 failed（❌）

# 流式模式（逐步返回，仅实时模式支持）
copaw agents chat \
  --agent-id my_bot \
  --to-agent helper_bot \
  --text "长篇分析任务" \
  --mode stream
```

**必填参数（实时模式）：**

- `--from-agent`（别名：`--agent-id`）：你的智能体 ID（发送方）
- `--to-agent`：目标智能体 ID（接收方）
- `--text`：消息内容

**后台任务参数（新增）：**

- `--background`：后台任务模式
- `--task-id`：查询后台任务状态（与 `--background` 一起使用）

**可选参数：**

- `--session-id`：多轮对话的会话 ID（省略时自动生成）
- `--mode`：响应模式 —— `final`（默认，完整响应）或 `stream`（逐步返回）
  - **注意**：`--background` 与 `--mode stream` 互斥
- `--base-url`：覆盖 API 地址
- `--timeout`：超时时间（秒，默认 300）
- `--json-output`：输出完整 JSON 而非纯文本

**后台模式说明：**

当任务复杂（如数据分析、批量处理、报告生成）时，使用 `--background` 可以避免阻塞当前智能体。提交后返回 `task_id`，稍后可以查询任务状态和结果。

**适用场景**：

- 数据分析和统计
- 批量文件处理
- 生成详细报告
- 调用慢速外部 API
- 不确定执行时间的复杂任务

**任务状态流程**：

- `submitted`：任务已接受，等待开始
- `pending`：排队等待执行
- `running`：正在执行
- `finished`：已完成（结果为 `completed` 成功或 `failed` 失败）

**说明：** `--from-agent` 和 `--agent-id` 等价，可互换使用。查询任务状态时只需 `--task-id`（`--to-agent` 为可选）。

**与 `copaw channels send` 的区别：**

- `copaw agents chat`：智能体间，双向，返回回复
- `copaw channels send`：智能体到用户/频道，单向，无回复

---

## 定时任务

让 CoPaw 按时间自动执行任务——「每天 9 点发消息」「每 2 小时提问并转发回复」。
**需要 `copaw app` 正在运行。**

### copaw cron

| 命令                         | 说明                           |
| ---------------------------- | ------------------------------ |
| `copaw cron list`            | 列出所有任务                   |
| `copaw cron get <job_id>`    | 查看任务配置                   |
| `copaw cron state <job_id>`  | 查看运行状态（下次运行时间等） |
| `copaw cron create ...`      | 创建任务                       |
| `copaw cron delete <job_id>` | 删除任务                       |
| `copaw cron pause <job_id>`  | 暂停任务                       |
| `copaw cron resume <job_id>` | 恢复暂停的任务                 |
| `copaw cron run <job_id>`    | 立刻执行一次                   |

**多智能体支持：** 所有命令都支持 `--agent-id` 参数（默认为 `default`）。

### 创建任务

**方式一——命令行参数（适合简单任务）**

任务分两种类型：

- **text** —— 到点向频道发一段固定文案。
- **agent** —— 到点向 CoPaw 提问，把回复发到频道。

```bash
# text：每天 9 点发「早上好！」到钉钉（默认智能体）
copaw cron create \
  --type text \
  --name "每日早安" \
  --cron "0 9 * * *" \
  --channel dingtalk \
  --target-user "你的用户ID" \
  --target-session "会话ID" \
  --text "早上好！"

# agent：为特定智能体创建任务
copaw cron create \
  --agent-id abc123 \
  --type agent \
  --name "检查待办" \
  --cron "0 */2 * * *" \
  --channel dingtalk \
  --target-user "你的用户ID" \
  --target-session "会话ID" \
  --text "我有什么待办事项？"
```

必填：`--type`、`--name`、`--cron`、`--channel`、`--target-user`、
`--target-session`、`--text`。

**方式二——JSON 文件（适合复杂或批量）**

```bash
copaw cron create -f job_spec.json
```

JSON 结构见 `copaw cron get <job_id>` 的返回。

### 额外选项

| 选项                         | 默认值   | 说明                                                  |
| ---------------------------- | -------- | ----------------------------------------------------- |
| `--timezone`                 | 用户时区 | Cron 调度时区（默认使用 config 中的 `user_timezone`） |
| `--enabled` / `--no-enabled` | 启用     | 创建时启用或禁用                                      |
| `--mode`                     | `final`  | `stream`（逐步发送）或 `final`（完成后一次性发送）    |
| `--base-url`                 | 自动     | 覆盖 API 地址                                         |

### Cron 表达式速查

五段式：**分 时 日 月 周**（无秒）。

| 表达式         | 含义          |
| -------------- | ------------- |
| `0 9 * * *`    | 每天 9:00     |
| `0 */2 * * *`  | 每 2 小时整点 |
| `30 8 * * 1-5` | 工作日 8:30   |
| `0 0 * * 0`    | 每周日 0:00   |
| `*/15 * * * *` | 每 15 分钟    |

---

## 会话管理

通过 API 管理聊天会话。**需要 `copaw app` 正在运行。**

### copaw chats

| 命令                                   | 说明                                               |
| -------------------------------------- | -------------------------------------------------- |
| `copaw chats list`                     | 列出所有会话（支持 `--user-id`、`--channel` 筛选） |
| `copaw chats get <id>`                 | 查看会话详情和消息历史                             |
| `copaw chats create ...`               | 创建新会话                                         |
| `copaw chats update <id> --name "..."` | 重命名会话                                         |
| `copaw chats delete <id>`              | 删除会话                                           |

**多智能体支持：** 所有命令都支持 `--agent-id` 参数（默认为 `default`）。

```bash
copaw chats list                        # 默认智能体的会话
copaw chats list --agent-id abc123      # 特定智能体的会话
copaw chats list --user-id alice --channel dingtalk
copaw chats get 823845fe-dd13-43c2-ab8b-d05870602fd8
copaw chats create --session-id "discord:alice" --user-id alice --name "My Chat"
copaw chats create --agent-id abc123 -f chat.json
copaw chats update <chat_id> --name "新名称"
copaw chats delete <chat_id>
```

---

## 技能

扩展 CoPaw 的能力（PDF 阅读、网页搜索等）。

### copaw skills

| 命令                  | 说明                              |
| --------------------- | --------------------------------- |
| `copaw skills list`   | 列出所有技能及启用/禁用状态       |
| `copaw skills config` | 交互式启用/禁用技能（复选框界面） |

**多智能体支持：** 所有命令都支持 `--agent-id` 参数（默认为 `default`）。

```bash
copaw skills list                   # 看默认智能体的技能
copaw skills list --agent-id abc123 # 看特定智能体的技能
copaw skills config                 # 交互式配置默认智能体
copaw skills config --agent-id abc123 # 交互式配置特定智能体
```

交互界面中：↑/↓ 选择、空格 切换、回车 确认。确认前会预览变更。

> 内置技能说明和自定义技能编写方法，请看 [技能](./skills)。

---

## 维护

### copaw clean

清空工作目录（默认 `~/.copaw`）下的所有内容。

```bash
copaw clean             # 交互确认
copaw clean --yes       # 不确认直接清空
copaw clean --dry-run   # 只列出会被删的内容，不删
```

---

## 全局选项

所有子命令都继承以下选项：

| 选项            | 默认值      | 说明                                      |
| --------------- | ----------- | ----------------------------------------- |
| `--host`        | `127.0.0.1` | API 地址（自动检测上次 `copaw app` 的值） |
| `--port`        | `8088`      | API 端口（自动检测上次 `copaw app` 的值） |
| `-h` / `--help` |             | 显示帮助                                  |

如果服务运行在非默认地址，全局传入即可：

```bash
copaw --host 0.0.0.0 --port 9090 cron list
```

## 工作目录

配置和数据都在 `~/.copaw`（默认）：

- **全局配置**: `config.json`（提供商、环境变量、智能体列表）
- **智能体工作区**: `workspaces/{agent_id}/`（每个智能体独立的配置和数据）

```
~/.copaw/
├── config.json              # 全局配置
└── workspaces/
    ├── default/             # 默认智能体工作区
    │   ├── agent.json       # 智能体配置
    │   ├── chats.json       # 对话历史
    │   ├── jobs.json        # 定时任务
    │   ├── AGENTS.md        # 人设文件
    │   └── memory/          # 记忆文件
    └── abc123/              # 其他智能体工作区
        └── ...
```

| 变量                | 说明             |
| ------------------- | ---------------- |
| `COPAW_WORKING_DIR` | 覆盖工作目录路径 |
| `COPAW_CONFIG_FILE` | 覆盖配置文件路径 |

详见 [配置与工作目录](./config) 和 [多智能体](./multi-agent)。

---

## 命令总览

| 命令             | 子命令                                                                                                                                 |  需要服务运行？   |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------------- | :---------------: |
| `copaw init`     | —                                                                                                                                      |        否         |
| `copaw app`      | —                                                                                                                                      | —（启动服务本身） |
| `copaw models`   | `list` · `config` · `config-key` · `set-llm` · `download` · `local` · `remove-local` · `ollama-pull` · `ollama-list` · `ollama-remove` |        否         |
| `copaw env`      | `list` · `set` · `delete`                                                                                                              |        否         |
| `copaw channels` | `list` · `send` · `install` · `add` · `remove` · `config`                                                                              |      **是**       |
| `copaw agents`   | `list` · `chat`                                                                                                                        |      **是**       |
| `copaw cron`     | `list` · `get` · `state` · `create` · `delete` · `pause` · `resume` · `run`                                                            |      **是**       |
| `copaw chats`    | `list` · `get` · `create` · `update` · `delete`                                                                                        |      **是**       |
| `copaw skills`   | `list` · `config`                                                                                                                      |        否         |
| `copaw clean`    | —                                                                                                                                      |        否         |

---

## 相关页面

- [项目介绍](./intro) —— CoPaw 可以做什么
- [控制台](./console) —— Web 管理界面
- [频道配置](./channels) —— 钉钉、飞书、iMessage、Discord、QQ 详细步骤
- [心跳](./heartbeat) —— 定时自检/摘要
- [技能](./skills) —— 内置技能与自定义技能
- [配置与工作目录](./config) —— 工作目录与 config.json
- [多智能体](./multi-agent) —— 多智能体配置、管理与协作
