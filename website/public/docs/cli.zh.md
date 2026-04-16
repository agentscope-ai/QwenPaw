# CLI

`qwenpaw` 是 QwenPaw 的命令行工具。本页按「上手 → 配置 → 日常管理」的顺序组织——
新用户从头读，老用户直接跳到需要的章节。

> 还不清楚「频道」「心跳」「定时任务」是什么？先看 [项目介绍](./intro)。

---

## 快速上手

第一次用 QwenPaw，只需要这两条命令。

### qwenpaw init

首次初始化，交互式引导你完成所有配置。

```bash
qwenpaw init              # 交互式初始化（推荐新用户）
qwenpaw init --defaults   # 不交互，用默认值（适合脚本）
qwenpaw init --force      # 覆盖已有配置文件
```

**交互流程（按顺序）：**

1. **默认工作区初始化** —— 自动创建默认工作区及配置文件。
2. **LLM 提供商** —— 选择提供商、输入 API Key、选择模型（**必选**）。
3. **环境变量** —— 可选添加工具所需的键值对。
4. **HEARTBEAT.md** —— 在默认编辑器中编辑心跳检查清单。

### qwenpaw app

启动 QwenPaw 服务。频道、定时任务、控制台等所有运行时功能都依赖此服务。

```bash
qwenpaw app                             # 默认 127.0.0.1:8088
qwenpaw app --reload                    # 代码改动自动重载（开发用）
qwenpaw app --log-level debug           # 详细日志
```

| 选项          | 默认值      | 说明                                                          |
| ------------- | ----------- | ------------------------------------------------------------- |
| `--host`      | `127.0.0.1` | 绑定地址                                                      |
| `--port`      | `8088`      | 绑定端口                                                      |
| `--reload`    | 关闭        | 文件变动时自动重载（仅开发用）                                |
| `--log-level` | `info`      | `critical` / `error` / `warning` / `info` / `debug` / `trace` |
| `--workers`   | —           | **[已废弃]** 将被忽略，QwenPaw 始终使用 1 个 worker           |

> **说明：** `--workers` 选项因稳定性原因已废弃。QwenPaw 被设计为单 worker 进程运行。多 worker 模式会导致内存状态管理和 WebSocket 连接出现问题。此选项将在未来版本中移除。

### 控制台

`qwenpaw app` 启动后，在浏览器打开 `http://127.0.0.1:8088/` 即可进入 **控制台** ——
一个用于对话、频道、定时任务、技能、模型等的 Web 管理界面。详见 [控制台](./console)。

若未构建前端，根路径会返回类似 `{"message": "QwenPaw Web Console is not available."}` 的提示信息（实际文案可能调整），API 仍可正常使用。

**构建方式：** 在项目 `console/` 目录下执行 `pnpm install && pnpm run build`，
然后将构建产物复制到包目录：
`mkdir -p src/qwenpaw/console && cp -R console/dist/. src/qwenpaw/console/`。
Docker 镜像或 pip 安装包已内置控制台，无需单独构建。

### qwenpaw daemon

查看运行状态、版本、最近日志等，无需启动对话。与在对话中发送 `/daemon status` 等效果一致（CLI 无进程时可查看本地信息）。

| 命令                           | 说明                                                                           |
| ------------------------------ | ------------------------------------------------------------------------------ |
| `qwenpaw daemon status`        | 状态（配置、工作目录、记忆服务）                                               |
| `qwenpaw daemon restart`       | 打印说明（在对话中用 /daemon restart 可进程内重载）                            |
| `qwenpaw daemon reload-config` | 重新读取并校验配置（频道/MCP 变更需在对话中 /daemon restart 或重启进程后生效） |
| `qwenpaw daemon version`       | 版本与路径                                                                     |
| `qwenpaw daemon logs [-n N]`   | 最近 N 行日志（默认 100，来自工作目录 `qwenpaw.log`）                          |

**多智能体支持：** 所有命令都支持 `--agent-id` 参数（默认为 `default`）。

```bash
qwenpaw daemon status                     # 默认智能体状态
qwenpaw daemon status --agent-id abc123   # 特定智能体状态
qwenpaw daemon version
qwenpaw daemon logs -n 50
```

### qwenpaw doctor

对当前安装做**只读**检查：根目录 `config.json` 校验、工作区、`agent.json`、
频道、MCP、控制台静态资源、HTTP API 可达性、活跃模型与各 Agent 模型连通性
等。**单独运行 `doctor` 不会修复磁盘**；需要改文件时请使用子命令
**`qwenpaw doctor fix`**（默认会在 `doctor-fix-backups/` 下备份后再写）。

```bash
qwenpaw doctor                      # 默认检查
qwenpaw doctor --deep               # 额外：已启用频道出站探测 + 本地 llama 提示
qwenpaw doctor --port 8088          # 强制指定 API 端口（见下文说明）
qwenpaw doctor fix --dry-run        # 仅打印计划，不写盘
qwenpaw doctor fix -y --only …      # 应用白名单内的修复项（详见 --help）
```

| 选项            | 作用对象 | 说明                                               |
| --------------- | -------- | -------------------------------------------------- |
| `--timeout`     | `doctor` | API / 连通性相关 HTTP 超时（默认 5 秒）            |
| `--llm-timeout` | `doctor` | 模型连通性检测超时（默认 15 秒）                   |
| `--deep`        | `doctor` | 对已启用频道做出站探测；`qwenpaw-local` 时附加说明 |

**`doctor` 连的是哪个 host/port？** 根命令上的 `qwenpaw --host` /
`--port` 对所有子命令生效（含 `doctor`）。若未指定，CLI 会用
**`config.json` 里持久化的 `last_api`**（一般在 `qwenpaw app` 启动时写入）
补全缺省项；**仅当没有 `last_api` 时**才回落到 `127.0.0.1:8088`。若发现
检查打到了错误端口，可显式加 `--port`，或改配置里的 `last_api`。

**`doctor fix`** 只会在工作目录范围内做保守修复。

#### 推荐流程（先预览，再执行）

```bash
qwenpaw doctor fix --dry-run
# 缩小到你明确想执行的修复项
qwenpaw doctor fix --dry-run --only ensure-working-dir,ensure-workspace-dirs

# 确认计划无误后再执行
qwenpaw doctor fix --only ensure-working-dir,ensure-workspace-dirs
```

- `--dry-run` 仅打印计划，不写盘。
- 若计划里包含只读校验（如 jobs.json 校验），FAIL 时仍会返回非 0 退出码
  （便于 CI 使用）。

#### 修复项（fix ids）

可通过 `--only` 传入逗号分隔的 id。

- 常见安示例：
  - `ensure-working-dir`：工作目录不存在时创建
  - `ensure-workspace-dirs`：创建缺失的 agent workspace 目录
- 完整 fix ids 列表与风险说明请查看：
  - `qwenpaw doctor fix --help`
- 当 `qwenpaw doctor` 检测到问题时，输出里会给出对应的修复提示（含建议
  的 `doctor fix --dry-run --only ...` 命令）。

#### 修复项的安全执行方式

示例：

```bash
qwenpaw doctor fix --dry-run --only seed-missing-agent-json,reset-invalid-agent-json
qwenpaw doctor fix -y --only seed-missing-agent-json,reset-invalid-agent-json
```

- `-y` 仅在真实执行（不带 `--dry-run`）时生效。
- `--non-interactive` 只允许安全 + 只读 + 技能同步类修复项

#### 备份与恢复

默认会写备份到：

- `doctor-fix-backups/<时间戳>/files/`

恢复时，将 `files/` 子树中的文件按相同相对路径复制回工作目录即可。

> 除非你非常确定不需要回滚，否则不建议使用 `--no-backup`。

---

## 模型与环境变量

使用 QwenPaw 前至少需要配置一个 LLM 提供商。环境变量为内置工具（如网页搜索）提供凭据。

### qwenpaw models

管理 LLM 提供商和活跃模型。

| 命令                                     | 说明                                   |
| ---------------------------------------- | -------------------------------------- |
| `qwenpaw models list`                    | 查看所有提供商、API Key 状态和当前模型 |
| `qwenpaw models config`                  | 完整交互式配置：API Key → 选择模型     |
| `qwenpaw models config-key [provider]`   | 单独配置某个提供商的 API Key           |
| `qwenpaw models set-llm`                 | 只切换活跃模型（不改 API Key）         |
| `qwenpaw models local`                   | 查看已下载的本地模型                   |
| `qwenpaw models download <repo_id>`      | 下载一个本地模型（llama.cpp）          |
| `qwenpaw models remove-local <model_id>` | 删除已下载的本地模型                   |

```bash
qwenpaw models list                    # 看当前状态
qwenpaw models config                  # 完整交互式配置
qwenpaw models config-key modelscope   # 只配 ModelScope 的 API Key
qwenpaw models config-key dashscope    # 只配 DashScope 的 API Key
qwenpaw models config-key custom       # 配置自定义提供商（Base URL + Key）
qwenpaw models set-llm                 # 只切换模型
```

#### 本地模型

QwenPaw 也支持通过 llama.cpp，Ollama 或 LM Studio 在本地运行模型——无需 API Key。
但在此之前需要先下载对应的应用，例如 [Ollama](https://ollama.com/download) 或 [LM Studio](https://lmstudio.ai/download)。

```bash
# 下载模型（自动选择 Q4_K_M GGUF）
qwenpaw models download Qwen/Qwen3-4B-GGUF

# 从 ModelScope 下载
qwenpaw models download Qwen/Qwen2-0.5B-Instruct-GGUF --source modelscope

# 查看已下载模型
qwenpaw models local

# 删除已下载模型
qwenpaw models remove-local <model_id>
qwenpaw models remove-local <model_id> --yes   # 跳过确认
```

| 选项       | 简写 | 默认值        | 说明                                           |
| ---------- | ---- | ------------- | ---------------------------------------------- |
| `--source` | `-s` | `huggingface` | 下载源（`huggingface` 或 `modelscope`）        |
| `--file`   | `-f` | _（自动）_    | 指定文件名。省略时自动选择（GGUF 优先 Q4_K_M） |

#### Ollama 模型

QwenPaw 集成 Ollama 以在本地运行模型。模型从 Ollama 守护进程动态加载——请先从 [ollama.com](https://ollama.com) 安装 Ollama。

安装 Ollama SDK：`pip install 'qwenpaw[ollama]'`（或使用 `--extras ollama` 重新运行安装脚本）

```bash
# 下载 Ollama 模型
ollama pull mistral:7b
ollama pull qwen2.5:3b

# 查看 Ollama 模型
ollama list

# 删除 Ollama 模型
ollama rm mistral:7b

# 在配置流程中使用（自动检测 Ollama 模型）
qwenpaw models config           # 选择 Ollama → 从模型列表中选择
qwenpaw models set-llm          # 切换到其他 Ollama 模型
```

**与本地模型的主要区别：**

- 模型来自 Ollama 守护进程（不由 QwenPaw 下载）
- 使用 `ollama` 命令管理模型（非 `qwenpaw models`）
- 通过 Ollama CLI 或 QwenPaw 添加/删除模型时，模型列表自动更新

> **注意：** API Key 的有效性需要用户自行保证，QwenPaw 不会验证。
> 详见 [配置 — 模型提供商](./config#模型提供商)。

### qwenpaw env

管理工具和技能在运行时使用的环境变量。

| 命令                        | 说明                 |
| --------------------------- | -------------------- |
| `qwenpaw env list`          | 列出所有已配置的变量 |
| `qwenpaw env set KEY VALUE` | 设置或更新变量       |
| `qwenpaw env delete KEY`    | 删除变量             |

```bash
qwenpaw env list
qwenpaw env set TAVILY_API_KEY "tvly-xxxxxxxx"
qwenpaw env set GITHUB_TOKEN "ghp_xxxxxxxx"
qwenpaw env delete TAVILY_API_KEY
```

> **注意：** QwenPaw 只负责存储和加载，值的有效性需要用户自行保证。
> 详见 [配置 — 环境变量](./config#环境变量)。

---

## 频道

将 QwenPaw 连接到消息平台。

### qwenpaw channels

管理频道配置（iMessage / Discord / DingTalk / Feishu / QQ / Console 等）并向频道发送消息。
**说明**：交互式配置用 `config`（无 `configure` 子命令）；卸载自定义频道用 `remove`（无 `uninstall`）。

**别名：** 可以用 `qwenpaw channel`（单数）作为 `qwenpaw channels` 的简写。

| 命令                             | 说明                                                                            |
| -------------------------------- | ------------------------------------------------------------------------------- |
| `qwenpaw channels list`          | 查看所有频道的状态（密钥脱敏）                                                  |
| `qwenpaw channels send`          | 向用户/会话单向发送消息（需要全部 5 个参数）                                    |
| `qwenpaw channels install <key>` | 在 `custom_channels/` 安装频道：创建模板，或用 `--path` / `--url` 安装          |
| `qwenpaw channels add <key>`     | 安装并加入 config；内置频道只写 config；支持 `--path` / `--url`                 |
| `qwenpaw channels remove <key>`  | 从 `custom_channels/` 删除自定义频道（内置不可删）；`--keep-config` 保留 config |
| `qwenpaw channels config`        | 交互式启用/禁用频道并填写凭据                                                   |

**多智能体支持：** 所有命令都支持 `--agent-id` 参数（默认为 `default`）。

```bash
qwenpaw channels list                    # 看默认智能体的频道状态
qwenpaw channels list --agent-id abc123  # 看特定智能体的频道状态
qwenpaw channels install my_channel      # 创建自定义频道模板
qwenpaw channels install my_channel --path ./my_channel.py
qwenpaw channels add dingtalk            # 把钉钉加入 config
qwenpaw channels remove my_channel       # 删除自定义频道（并默认从 config 移除）
qwenpaw channels remove my_channel --keep-config   # 只删模块，保留 config 条目
qwenpaw channels config                  # 交互式配置默认智能体
qwenpaw channels config --agent-id abc123 # 交互式配置特定智能体
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

使用 `qwenpaw channels send` 主动向用户/会话推送消息，支持所有已配置的频道。这是**单向发送** —— 不会返回回复。

智能体通过启用 **channel_message** 技能，可以在需要时自动使用此命令向用户发送主动通知。

**典型使用场景：**

- 任务完成后主动通知用户
- 定时提醒、告警、状态更新
- 将异步处理结果推送回原会话
- 用户明确要求"处理完后通知我"

```bash
# 第一步：查询可用会话
qwenpaw chats list --agent-id my_bot --channel feishu

# 第二步：使用查询到的参数发送消息
qwenpaw channels send \
  --agent-id my_bot \
  --channel feishu \
  --target-user ou_xxxx \
  --target-session session_id_xxxx \
  --text "任务已完成！"
```

**必填参数（全部 5 个）：**

- `--agent-id`：发送方智能体 ID
- `--channel`：目标频道（console/dingtalk/feishu/discord/imessage/qq）
- `--target-user`：用户 ID（从 `qwenpaw chats list` 获取）
- `--target-session`：会话 ID（从 `qwenpaw chats list` 获取）
- `--text`：消息内容

**重要提示：**

- 发送前必须先用 `qwenpaw chats list` 查询 —— 不要猜测 `target-user` 或 `target-session`
- 如果有多个会话，优先使用最近更新的
- 这仅用于主动通知；智能体间通信请用 `qwenpaw agents chat`（见下方"智能体"章节）

**与 `qwenpaw agents chat` 的区别：**

- `qwenpaw channels send`：智能体向用户/频道推送，单向，无回复
- `qwenpaw agents chat`：智能体间通信，双向，有回复

---

## 智能体

管理智能体并支持智能体间通信。

### qwenpaw agents

> 对应技能：**Multi-Agent Collaboration（多智能体协作）**

智能体通过启用 **multi_agent_collaboration** 技能，可以在需要时自动使用 `qwenpaw agents chat` 与其他智能体协作。

**别名：** 可以用 `qwenpaw agent`（单数）作为 `qwenpaw agents` 的简写。

| 命令                  | 说明                                             |
| --------------------- | ------------------------------------------------ |
| `qwenpaw agents list` | 列出所有已配置的智能体（ID、名称、描述、工作区） |
| `qwenpaw agents chat` | 与另一个智能体通信（双向，支持多轮对话）         |

```bash
# 列出所有智能体
qwenpaw agents list
qwenpaw agent list  # 单数别名效果相同

# 与另一个智能体对话（实时模式，单次）
qwenpaw agents chat \
  --agent-id my_bot \
  --to-agent helper_bot \
  --text "请帮我分析这些数据"

# 多轮对话（session 复用）
qwenpaw agents chat \
  --agent-id my_bot \
  --to-agent helper_bot \
  --session-id collab_session_001 \
  --text "继续上一个问题"

# 复杂任务（后台模式）
qwenpaw agents chat --background \
  --agent-id my_bot \
  --to-agent data_analyst \
  --text "分析 /data/logs/2026-03-26.log 并生成详细报告"
# 返回 [TASK_ID: xxx] [SESSION: xxx]

# 查询后台任务状态（查询时 --to-agent 为可选）
qwenpaw agents chat --background \
  --task-id <task_id>
# 状态流程：submitted → pending → running → finished
# finished 时结果显示：completed（✅）或 failed（❌）

# 流式模式（逐步返回，仅实时模式支持）
qwenpaw agents chat \
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

**与 `qwenpaw channels send` 的区别：**

- `qwenpaw agents chat`：智能体间，双向，返回回复
- `qwenpaw channels send`：智能体到用户/频道，单向，无回复

---

## 定时任务

让 QwenPaw 按时间自动执行任务——「每天 9 点发消息」「每 2 小时提问并转发回复」。
**需要 `qwenpaw app` 正在运行。**

### qwenpaw cron

| 命令                           | 说明                           |
| ------------------------------ | ------------------------------ |
| `qwenpaw cron list`            | 列出所有任务                   |
| `qwenpaw cron get <job_id>`    | 查看任务配置                   |
| `qwenpaw cron state <job_id>`  | 查看运行状态（下次运行时间等） |
| `qwenpaw cron create ...`      | 创建任务                       |
| `qwenpaw cron delete <job_id>` | 删除任务                       |
| `qwenpaw cron pause <job_id>`  | 暂停任务                       |
| `qwenpaw cron resume <job_id>` | 恢复暂停的任务                 |
| `qwenpaw cron run <job_id>`    | 立刻执行一次                   |

**多智能体支持：** 所有命令都支持 `--agent-id` 参数（默认为 `default`）。

### 创建任务

**方式一——命令行参数（适合简单任务）**

任务分两种类型：

- **text** —— 到点向频道发一段固定文案。
- **agent** —— 到点向 QwenPaw 提问，把回复发到频道。

```bash
# text：每天 9 点发「早上好！」到钉钉（默认智能体）
qwenpaw cron create \
  --type text \
  --name "每日早安" \
  --cron "0 9 * * *" \
  --channel dingtalk \
  --target-user "你的用户ID" \
  --target-session "会话ID" \
  --text "早上好！"

# agent：为特定智能体创建任务
qwenpaw cron create \
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
qwenpaw cron create -f job_spec.json
```

JSON 结构见 `qwenpaw cron get <job_id>` 的返回。

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

通过 API 管理聊天会话。**需要 `qwenpaw app` 正在运行。**

### qwenpaw chats

| 命令                                     | 说明                                               |
| ---------------------------------------- | -------------------------------------------------- |
| `qwenpaw chats list`                     | 列出所有会话（支持 `--user-id`、`--channel` 筛选） |
| `qwenpaw chats get <id>`                 | 查看会话详情和消息历史                             |
| `qwenpaw chats create ...`               | 创建新会话                                         |
| `qwenpaw chats update <id> --name "..."` | 重命名会话                                         |
| `qwenpaw chats delete <id>`              | 删除会话                                           |

**多智能体支持：** 所有命令都支持 `--agent-id` 参数（默认为 `default`）。

```bash
qwenpaw chats list                        # 默认智能体的会话
qwenpaw chats list --agent-id abc123      # 特定智能体的会话
qwenpaw chats list --user-id alice --channel dingtalk
qwenpaw chats get 823845fe-dd13-43c2-ab8b-d05870602fd8
qwenpaw chats create --session-id "discord:alice" --user-id alice --name "My Chat"
qwenpaw chats create --agent-id abc123 -f chat.json
qwenpaw chats update <chat_id> --name "新名称"
qwenpaw chats delete <chat_id>
```

---

## 技能

扩展 QwenPaw 的能力（PDF 阅读、网页搜索等）。

### qwenpaw skills

| 命令                    | 说明                              |
| ----------------------- | --------------------------------- |
| `qwenpaw skills list`   | 列出所有技能及启用/禁用状态       |
| `qwenpaw skills config` | 交互式启用/禁用技能（复选框界面） |

**多智能体支持：** 所有命令都支持 `--agent-id` 参数（默认为 `default`）。

```bash
qwenpaw skills list                   # 看默认智能体的技能
qwenpaw skills list --agent-id abc123 # 看特定智能体的技能
qwenpaw skills config                 # 交互式配置默认智能体
qwenpaw skills config --agent-id abc123 # 交互式配置特定智能体
```

交互界面中：↑/↓ 选择、空格 切换、回车 确认。确认前会预览变更。

> 内置技能说明和自定义技能编写方法，请看 [技能](./skills)。

---

## 维护

### qwenpaw clean

清空工作目录（默认 `~/.qwenpaw`）下的所有内容。

```bash
qwenpaw clean             # 交互确认
qwenpaw clean --yes       # 不确认直接清空
qwenpaw clean --dry-run   # 只列出会被删的内容，不删
```

---

## 全局选项

所有子命令都继承以下选项：

| 选项            | 默认值      | 说明                                        |
| --------------- | ----------- | ------------------------------------------- |
| `--host`        | `127.0.0.1` | API 地址（自动检测上次 `qwenpaw app` 的值） |
| `--port`        | `8088`      | API 端口（自动检测上次 `qwenpaw app` 的值） |
| `-h` / `--help` |             | 显示帮助                                    |

如果服务运行在非默认地址，全局传入即可：

```bash
qwenpaw --host 0.0.0.0 --port 9090 cron list
```

## 工作目录

配置和数据都在 `~/.qwenpaw`（默认）：

- **全局配置**: `config.json`（提供商、环境变量、智能体列表）
- **智能体工作区**: `workspaces/{agent_id}/`（每个智能体独立的配置和数据）

```
~/.qwenpaw/
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

| 变量                  | 说明             |
| --------------------- | ---------------- |
| `QWENPAW_WORKING_DIR` | 覆盖工作目录路径 |
| `QWENPAW_CONFIG_FILE` | 覆盖配置文件路径 |

详见 [配置与工作目录](./config) 和 [多智能体](./multi-agent)。

---

## 命令总览

| 命令               | 子命令                                                                               |  需要服务运行？   |
| ------------------ | ------------------------------------------------------------------------------------ | :---------------: |
| `qwenpaw init`     | —                                                                                    |        否         |
| `qwenpaw app`      | —                                                                                    | —（启动服务本身） |
| `qwenpaw models`   | `list` · `config` · `config-key` · `set-llm` · `download` · `local` · `remove-local` |        否         |
| `qwenpaw env`      | `list` · `set` · `delete`                                                            |        否         |
| `qwenpaw channels` | `list` · `send` · `install` · `add` · `remove` · `config`                            |      **是**       |
| `qwenpaw agents`   | `list` · `chat`                                                                      |      **是**       |
| `qwenpaw cron`     | `list` · `get` · `state` · `create` · `delete` · `pause` · `resume` · `run`          |      **是**       |
| `qwenpaw chats`    | `list` · `get` · `create` · `update` · `delete`                                      |      **是**       |
| `qwenpaw skills`   | `list` · `config`                                                                    |        否         |
| `qwenpaw clean`    | —                                                                                    |        否         |

---

## 相关页面

- [项目介绍](./intro) —— QwenPaw 可以做什么
- [控制台](./console) —— Web 管理界面
- [频道配置](./channels) —— 钉钉、飞书、iMessage、Discord、QQ 详细步骤
- [心跳](./heartbeat) —— 定时自检/摘要
- [技能](./skills) —— 内置技能与自定义技能
- [配置与工作目录](./config) —— 工作目录与 config.json
- [多智能体](./multi-agent) —— 多智能体配置、管理与协作
