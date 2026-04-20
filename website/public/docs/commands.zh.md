# 魔法命令

魔法命令是一组以 `/` 开头的特殊指令，让你可以**直接控制对话状态**，而不需要等 AI 理解你的意图。

---

## 对话管理命令

控制对话上下文的命令。

| 命令       | 需要等待 | 压缩摘要      | 长期记忆    | 返回内容             |
| ---------- | -------- | ------------- | ----------- | -------------------- |
| `/compact` | ⏳ 是    | 📦 生成新摘要 | ✅ 后台保存 | ✅ 压缩完成 + 新摘要 |
| `/new`     | ⚡ 否    | 🗑️ 清空       | ✅ 后台保存 | ✅ 新对话开始提示    |
| `/clear`   | ⚡ 否    | 🗑️ 清空       | ❌ 不保存   | ✅ 历史清空提示      |

---

### /compact - 压缩当前对话

手动触发对话压缩，将当前对话消息浓缩成摘要（**需要等待**），同时后台保存到长期记忆。

```
/compact
```

也可以额外补一句说明，指导摘要保留或删除哪些信息：

```
/compact 保留需求、决策和待办，去掉调试日志和工具调用细节
```

**返回示例：**

```
**Compact Complete!**

- Messages compacted: 12
**Compressed Summary:**
用户请求帮助构建用户认证系统，已完成登录接口的实现...
- Summary task started in background
```

> 💡 与自动压缩不同，`/compact` 会压缩**所有**当前消息，而不是只压缩超出阈值的部分。
> 💡 额外说明只作用于这一次手动 `/compact`，不会改变自动压缩行为。

---

### /new - 清空上下文并保存记忆

**立即清空当前上下文**，开始全新对话。后台同时保存历史到长期记忆。

```
/new
```

**返回示例：**

```
**New Conversation Started!**

- Summary task started in background
- Ready for new conversation
```

---

### /clear - 清空上下文（不保存记忆）

**立即清空当前上下文**，包括消息历史和压缩摘要。**不会**保存到长期记忆。

```
/clear
```

**返回示例：**

```
**History Cleared!**

- Compressed summary reset
- Memory is now empty
```

> ⚠️ **警告**：`/clear` 是**不可逆**的！与 `/new` 不同，清除的内容不会被保存。

---

## 对话调试命令

查看和管理对话历史的命令。

| 命令            | 返回内容                 |
| --------------- | ------------------------ |
| `/history`      | 📋 消息列表 + Token 统计 |
| `/message`      | 📄 指定消息详情          |
| `/compact_str`  | 📝 压缩摘要内容          |
| `/dump_history` | 📁 历史导出文件路径      |
| `/load_history` | ✅ 历史加载结果          |

---

### /history - 查看当前对话历史

显示当前对话中所有未压缩的消息列表，以及详细的**上下文占用情况**。

```
/history
```

**返回示例：**

```
**Conversation History**

- Total messages: 3
- Estimated tokens: 1256
- Max input length: 128000
- Context usage: 0.98%
- Compressed summary tokens: 128

[1] **user** (text_tokens=42)
    content: [text(tokens=42)]
    preview: 帮我写一个 Python 函数...

[2] **assistant** (text_tokens=256)
    content: [text(tokens=256)]
    preview: 好的，我来帮你写一个函数...

[3] **user** (text_tokens=28)
    content: [text(tokens=28)]
    preview: 能不能加上错误处理？

---

- Use /message <index> to view full message content
- Use /compact_str to view full compact summary
```

> 💡 **提示**：建议多使用 `/history` 命令了解当前上下文占用情况。
>
> 当 `Context usage` 接近 75% 时，对话即将触发自动 `compact`。
>
> 如果出现上下文超过最大上限的情况，请向社区反馈对应的模型和 `/history` 日志，然后主动使用 `/compact` 或 `/new` 来管理上下文。
>
> Token计算逻辑详见 [ReMeInMemoryMemory 实现](https://github.com/agentscope-ai/ReMe/blob/v0.3.0.6b2/reme/memory/file_based/reme_in_memory_memory.py#L122)。

---

### /message - 查看单条消息

查看当前对话中指定索引的消息详细内容。

```
/message <index>
```

**参数：**

- `index` - 消息索引号（从 1 开始）

**示例：**

```
/message 1
```

**输出：**

```
**Message 1/3**

- **Timestamp:** 2024-01-15 10:30:00
- **Name:** user
- **Role:** user
- **Content:**
帮我写一个 Python 函数，实现快速排序算法
```

---

### /compact_str - 查看压缩摘要

显示当前的压缩摘要内容。

```
/compact_str
```

**返回示例（有摘要时）：**

```
**Compressed Summary**

用户请求帮助构建用户认证系统，已完成登录接口的实现...
```

**返回示例（无摘要时）：**

```
**No Compressed Summary**

- No summary has been generated yet
- Use /compact or wait for auto-compaction
```

---

### /dump_history - 导出对话历史

将当前对话历史（包括压缩摘要）保存到 JSONL 文件，便于调试和备份。

```
/dump_history
```

**返回示例：**

```
**History Dumped!**

- Messages saved: 15
- Has summary: True
- File: `/path/to/workspace/debug_history.jsonl`
```

> 💡 **提示**：导出的文件可用于 `/load_history` 恢复对话历史，也可用于调试分析。

---

### /load_history - 加载对话历史

从 JSONL 文件加载对话历史到当前内存，**会先清空现有内存**。

```
/load_history
```

**返回示例：**

```
**History Loaded!**

- Messages loaded: 15
- Has summary: True
- File: `/path/to/workspace/debug_history.jsonl`
- Memory cleared before loading
```

**注意事项：**

- 文件来源：从工作目录下的 `debug_history.jsonl` 加载
- 最大加载：10000 条消息
- 如果文件第一条消息包含压缩摘要标记，会自动恢复压缩摘要
- 加载前会**清空当前内存**，请确保已备份重要内容

> ⚠️ **警告**：`/load_history` 会清空当前内存后再加载，现有对话将丢失！

---

## Skill 聊天命令

提供以下命令，在聊天中可以访问 skill 状态，并强制 Agent 使用某个
skill。

- `/skills` 会以精简格式列出当前频道可用的 skill。
- `/<skill_name>` 会显示该 skill 的详细信息，包括 description 和本地
  path。
- `/<skill_name> <input>` 会使 Agent 强制调用 `skill_name`，解决 input
  （通常是个任务）。
- `/[skill_name]` 也支持以上操作，可作为另一种写法。

说明：

- `skill_name` 以 `/skills` 里显示的技能命令名为准。
- 这些斜杠命令只对当前频道中已启用且路由到该频道的 skill 生效。

---

## 模型管理命令

管理和切换 AI 模型的命令，无需通过 Agent 理解意图，直接执行。

| 命令                             | 说明                   | 对话 |
| -------------------------------- | ---------------------- | ---- |
| `/model`                         | 显示当前使用的模型     | ✅   |
| `/model -h` 或 `/model help`     | 显示帮助信息           | ✅   |
| `/model list`                    | 列出所有可用模型       | ✅   |
| `/model <provider>:<model>`      | 切换到指定模型         | ✅   |
| `/model reset`                   | 重置为全局默认模型     | ✅   |
| `/model info <provider>:<model>` | 显示指定模型的详细信息 | ✅   |

---

### `/model` - 显示当前模型

显示当前 Agent 正在使用的模型。

**用法：**

```
/model
```

**返回示例：**

```
**Current Model**

Provider: `openai`
Model: `gpt-4o` ✓

Use `/model list` to see all available models.
```

---

### `/model -h` 或 `/model help` - 显示帮助

显示所有 `/model` 命令的帮助信息。

**用法：**

```
/model -h
/model --help
/model help
```

**返回示例：**

```
**Model Management Commands**

Manage and switch AI models for the current agent.

**Available Commands:**

`/model` - Show current active model
`/model list` - List all available models
`/model <provider>:<model>` - Switch to specified model
`/model reset` - Reset to global default model
`/model info <provider>:<model>` - Show model information
`/model help` or `/model -h` - Show this help message

**Examples:**

`/model` - Show current model
`/model list` - List all models
`/model openai:gpt-4o` - Switch to GPT-4o
`/model reset` - Reset to global default
`/model info openai:gpt-4o` - Show GPT-4o information

**Capability Indicators:**

🖼️ - Supports image input
🎥 - Supports video input
```

---

### `/model list` - 列出所有模型

显示所有已配置的 Provider 及其可用模型。当前激活的模型会标记为 **[ACTIVE]**。

**用法：**

```
/model list
```

**返回示例：**

```
**Available Models**

**OpenAI** (`openai`)
  - `gpt-4o` 🖼️ **[ACTIVE]**
  - `gpt-4o-mini` 🖼️
  - `gpt-3.5-turbo`
  - `my-custom-model` *(user-added)*

**Anthropic** (`anthropic`)
  - `claude-3-5-sonnet-20241022`
  - `claude-3-opus-20240229`

**Google** (`gemini`)
  - `gemini-2.0-flash-exp` 🖼️🎥

---
Total: 3 provider(s), 8 model(s)

Use `/model <provider>:<model>` to switch models.
Example: `/model openai:gpt-4o`
```

**标识说明：**

- 🖼️ - 支持图片输入
- 🎥 - 支持视频输入
- _(user-added)_ - 用户手动添加的模型（通过 `qwenpaw models add-model` 命令）

---

### `/model <provider>:<model>` - 切换模型

将当前 Agent 切换到使用不同的模型。

**用法：**

```
/model <provider>:<model>
```

**示例：**

```
/model openai:gpt-4o
/model anthropic:claude-3-5-sonnet-20241022
/model gemini:gemini-2.0-flash-exp
```

**返回示例：**

```
**Model Switched**

Provider: `anthropic`
Model: `claude-3-5-sonnet-20241022`

The new model will be used for subsequent messages.
```

> 💡 **提示**：模型切换只影响当前 Agent，其他 Agent 继续使用各自配置的模型。

---

### `/model reset` - 重置为全局默认模型

将当前 Agent 的模型重置为在 Web UI 中配置的全局默认模型。

**用法：**

```
/model reset
```

**返回示例：**

```
**Model Reset**

Agent model has been reset to global default:

Provider: `openai`
Model: `gpt-4o`

The global default model will be used for subsequent messages.
```

> 💡 **提示**：使用此命令可以撤销 Agent 级别的模型覆盖设置。

---

### `/model info` - 显示模型信息

显示指定模型的详细信息，包括能力和当前状态。

**用法：**

```
/model info <provider>:<model>
```

**示例：**

```
/model info openai:gpt-4o
/model info anthropic:claude-3-5-sonnet-20241022
```

**返回示例：**

```
**Model Information**

**Provider:** `openai` (OpenAI)
**Model ID:** `gpt-4o`
**Model Name:** GPT-4o
**Capabilities:** 🖼️ Image, 🎨 Multimodal
**Probe Source:** documentation

**Status:** ✓ Currently active

---
Use `/model openai:gpt-4o` to switch to this model.
```

---

## 系统控制命令

控制和监控 QwenPaw 运行状态的命令，无需通过 Agent 理解意图，直接执行。

可在对话中发送 `/daemon <子命令>` 或短名（如 `/status`），也可在终端执行 `qwenpaw daemon <子命令>`。

| 命令                                | 说明                                                                         | 对话 | 终端 |
| ----------------------------------- | ---------------------------------------------------------------------------- | ---- | ---- |
| `/stop`                             | 立即终止当前会话的运行中任务                                                 | ✅   | ❌   |
| `/stop session=<session_id>`        | 终止指定会话的任务                                                           | ✅   | ❌   |
| `/daemon status` 或 `/status`       | 查看运行状态（配置、工作目录、记忆服务）                                     | ✅   | ✅   |
| `/daemon restart` 或 `/restart`     | 零停机重载（对话中）；终端中打印说明                                         | ✅   | ✅   |
| `/daemon reload-config`             | 重新读取并校验配置文件                                                       | ✅   | ✅   |
| `/daemon version`                   | 版本号、工作目录与日志路径                                                   | ✅   | ✅   |
| `/daemon logs` 或 `/daemon logs 50` | 查看最近 N 行日志（默认 100 行，最大 2000 行，来自工作目录下 `qwenpaw.log`） | ✅   | ✅   |
| `/daemon approve`                   | 批准待审的工具调用（工具审批场景）                                           | ✅   | ❌   |

---

### `/stop` - 停止任务

立即终止当前会话中正在执行的任务。优先级最高，即使有任务正在执行也能并发处理。

**用法：**

```
/stop                       # 停止当前会话的任务
/stop session=<session_id>  # 停止指定会话的任务
```

> ⚠️ **警告**：`/stop` 会立即终止任务，可能导致部分结果丢失。

---

### `/daemon status` 或 `/status` - 查看运行状态

显示当前运行状态，包括配置加载情况、工作目录、记忆服务状态等。

**用法：**

```
/status                    # 在对话中
qwenpaw daemon status        # 在终端
```

---

### `/daemon restart` 或 `/restart` - 零停机重载

在对话中使用时，执行零停机重载：重新加载 channels、cron、MCP 配置，但不中断进程。适用于修改频道、MCP 配置后使其生效。

**用法：**

```
/restart                   # 在对话中
qwenpaw daemon restart       # 在终端（仅打印说明）
```

> 💡 **提示**：修改频道或 MCP 配置后，先用 `/daemon reload-config` 验证配置正确性，再用 `/daemon restart` 使其生效。

---

### `/daemon reload-config` - 重载配置文件

重新读取配置文件并校验语法，但不重载运行时组件（channels、cron、MCP）。适用于验证配置文件修改是否正确。

**用法：**

```
/daemon reload-config           # 在对话中
qwenpaw daemon reload-config      # 在终端
```

---

### `/daemon version` - 版本信息

显示 QwenPaw 版本号、工作目录路径、日志文件路径。

**用法：**

```
/daemon version            # 在对话中
qwenpaw daemon version       # 在终端
```

---

### `/daemon logs` - 查看日志

查看工作目录下 `qwenpaw.log` 的最近 N 行日志。默认 100 行，最大 2000 行。

**用法：**

```
/daemon logs               # 默认 100 行
/daemon logs 50            # 指定 50 行
qwenpaw daemon logs -n 200   # 在终端指定 200 行
```

> 💡 **提示**：日志文件较大时，此命令只读取文件末尾最多 512KB 内容，确保响应速度。

---

### `/daemon approve` - 批准工具调用

快速批准待审的工具调用。当工具调用需要人工审批时（tool-guard 场景），使用此命令批准执行。

**用法：**

```
/daemon approve            # 在对话中
```

> 💡 **提示**：此命令仅在对话中有效。当 Agent 提示需要批准工具调用时，发送此命令即可快速批准。

---

### 终端使用

所有 daemon 命令都支持在终端中使用（除 `/stop` 和 `/daemon approve` 仅在对话中有效）：

```bash
qwenpaw daemon status
qwenpaw daemon restart
qwenpaw daemon reload-config
qwenpaw daemon version
qwenpaw daemon logs -n 50
```

**多智能体支持：** 所有终端命令都支持 `--agent-id` 参数（默认为 `default`）。

```bash
qwenpaw daemon status --agent-id abc123
qwenpaw daemon version --agent-id abc123
```

---

## Mission Mode - 复杂任务自主执行

Mission Mode 是一个专为**长期、复杂任务**设计的自主执行模式，灵感来自 [Claude Code](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) 和 [Ralph Loop](https://github.com/snarktank/ralph)。它将大型任务拆解为多个用户故事（user stories），并通过 **master agent → worker agents → verifier agents** 的流水线完成，确保质量和可靠性。

### 核心特性

- 📋 **两阶段设计**：Phase 1 生成 PRD（产品需求文档），Phase 2 自动执行
- 🔒 **代码级控制**：Master agent 禁用实现工具，只能调度 worker，防止上下文污染
- ✅ **独立验证**：每个 story 由专门的 verifier agent 验证，确保通过所有验收标准
- 🔄 **自动迭代**：未通过的 story 自动重试，直到所有 story 完成或达到最大迭代次数
- 🌐 **多语言支持**：自动根据 agent 配置返回中文或英文错误消息

### 适用场景

**✅ 适合 Mission Mode 的任务：**

- 构建完整的功能模块（如用户认证系统、文件管理器）
- 重构大型代码库（如迁移到新框架）
- 批量任务（如为多个组件添加单元测试）
- 需要多次迭代验证的任务

**❌ 不适合 Mission Mode 的任务：**

- 简单的代码修改（如修改一个 bug）
- 需要实时交互的任务（如调试）
- 探索性任务（如"研究最佳实践"）

### 基本用法

#### 启动 Mission

```bash
/mission <任务描述>
```

**示例：**

```
/mission 创建一个命令行 TODO 应用，使用 Python，支持添加、删除、列出和标记完成任务，数据保存到本地 JSON 文件
```

**可选参数：**

- `--max-iterations N`: 设置 Phase 2 最大迭代次数（范围 1-100，默认 20）
- `--verify <command>`: 自定义验证命令（如 `pytest`）

```
/mission 创建 Web API --max-iterations 30 --verify "pytest tests/"
```

#### Phase 1: PRD 生成

Agent 会：

1. 探索代码库，理解现有结构
2. 将任务拆解为多个用户故事
3. 生成 `prd.json` 文件，包含每个 story 的验收标准

**PRD 示例：**

```json
{
  "project": "todo-cli-app",
  "description": "命令行 TODO 应用",
  "userStories": [
    {
      "id": "US-001",
      "title": "添加任务功能",
      "description": "As a user, I want to add new tasks...",
      "acceptanceCriteria": [
        "命令 'todo add <task>' 可成功添加任务",
        "任务保存到 todos.json 文件"
      ],
      "priority": 1,
      "passes": false
    }
  ]
}
```

#### Phase 2: 确认并执行

**确认 PRD：**

查看 PRD 后，发送确认消息进入 Phase 2：

```
确认，开始执行
```

**或者，如果需要修改：**

```
请把 US-001 拆分为两个 story，分别处理添加和持久化
```

Agent 会修改 PRD，再次等待确认。

**Phase 2 执行流程：**

1. **Master 调度**：分派 worker agent 执行每个 story
2. **Worker 实现**：创建/修改文件，运行测试
3. **Verifier 验证**：独立 agent 验证是否通过所有验收标准
4. **更新 PRD**：通过的 story 标记 `passes: true`
5. **自动迭代**：未通过的 story 重新分派，直到全部完成

#### 查看进度

```bash
/mission status
```

**输出示例：**

```
**Mission Status** — mission-20260415-123456
- Session: e2e-abc123
- Phase: execution
- Project: todo-cli-app
- Progress: 2/4 stories passed
- Loop dir: ~/.copaw/workspaces/default/missions/mission-20260415-123456

  ✅ US-001: 添加任务功能
  ✅ US-002: 列出任务功能
  ⬜ US-003: 删除任务功能
  ⬜ US-004: 标记完成功能
```

#### 列出所有 Mission

```bash
/mission list
```

### 工作目录结构

每个 mission 在 `~/.copaw/workspaces/default/missions/mission-<timestamp>/` 下创建工作目录：

```
mission-20260415-123456/
├── prd.json              # 产品需求文档
├── loop_config.json      # 配置和状态
├── task.md               # 原始任务描述
├── progress.txt          # 进度日志（Codebase Patterns）
└── <实现产出的文件>
```

### 注意事项

1. **Session 隔离**：每个 session 的 mission 相互独立，不会互相干扰
2. **PRD 格式校验**：Phase 2 启动前会强制校验 PRD 格式，确保符合 schema
3. **工具限制**：Phase 2 中，master agent **不能**直接使用 `edit_file`、`browser_use` 等实现工具，只能通过 worker 完成
4. **迭代上限**：达到 `--max-iterations` 后自动停止，避免无限循环
5. **Git 支持**：如果工作目录是 Git 仓库，agent 会自动 commit 变更（可选）
6. **⚠️ 工具安全护栏绕过**：
   - **Worker 和 verifier agents 会自动绕过安全护栏**（通过 `--background` 模式自动禁用）
   - 这是因为后台 session 无法响应 `/approve` 交互提示
   - Master agent 也会绕过护栏保护
   - **安全提示**：所有 worker 操作都在 `missions/<mission-xxx>/` 目录下进行，但仍建议**仅在完全信任的代码仓库中使用 Mission Mode**
   - 敏感操作（如删除文件、执行 shell 命令）会直接执行，无需人工审批

### 高级用法

#### 自定义验证命令

```
/mission 添加单元测试 --verify "npm test"
```

验证阶段会运行 `npm test` 检查是否通过。

#### 增加迭代次数（复杂任务）

```
/mission 重构整个认证模块 --max-iterations 50
```

#### 中途介入

Phase 2 执行过程中，可以随时发送消息与 master agent 交互：

```
暂停一下，US-003 的实现有问题，请修复后再继续
```

### 故障排查

**问题：PRD 格式不正确**

```
⚠️ **无法进入 Phase 2**: prd.json 格式错误:
  - Missing required field: userStories

请修正 PRD 格式后再确认。
```

**解决**：检查 `prd.json`，确保包含 `userStories` 数组，每个 story 有必需字段。

**问题：达到最大迭代次数**

```
⚠️ **Mission reached max iterations** (20). 2/4 stories passed.
```

**解决**：

1. 使用 `/mission status` 查看剩余 story
2. 增加 `--max-iterations` 重新启动
3. 或手动完成剩余工作

### 与其他模式的对比

| 模式             | 适用场景           | Agent 行为          | 工具使用        |
| ---------------- | ------------------ | ------------------- | --------------- |
| **普通对话**     | 简单任务、快速修改 | 单 agent 直接执行   | 所有工具可用    |
| **Mission Mode** | 复杂、长期任务     | Master 调度 workers | Master 限制工具 |

---

## Proactive Mode - 主动提醒模式

Proactive Mode（主动提醒模式）是一个智能化的功能，允许 AI 代理在检测到用户长时间未活动后，主动分析用户当前的会话上下文和屏幕活动，并提供相关的帮助和信息。

### 核心特性

- 🤖 **智能检测**：监控用户会话活动状态，当检测到设定时间内的无活动时触发
- 🧠 **上下文分析**：分析用户的对话历史和当前屏幕内容，识别潜在需求
- 🔍 **目标提取**：从对话历史中提取用户可能关注的高频或近期主题
- 💬 **主动响应**：基于分析结果，自动生成友好且相关的主动帮助信息

### 重要提示

**启用此模式前请务必知悉以下风险：**

- **工具防护绕过**：在此模式下，Agent会绕过标准的工具防护机制，Agent 拥有更高的系统权限和执行自由度
- **隐私与环境访问**：Agent会读取历史会话记忆以理解上下文，并可能进行截屏以获取当前的运行环境信息。请确保在可信环境中使用，并注意敏感信息的保护
- 本模式默认不启用，仅在用户主动开启时才生效，且可在开启后关闭

### 基本用法

#### 启用主动提醒模式

```bash
/proactive
/proactive <分钟数>
```

**示例：**

```bash
/proactive      # 默认30分钟后如果没有活动则触发主动提醒
/proactive 60   # 60分钟后触发主动提醒
```

#### 停用主动提醒模式

```bash
/proactive off
```

### 工作原理

1. **监控阶段**：持续监控用户活动，记录最后活动时间戳
2. **分析阶段**：当检测到超过设定的空闲时间后，分析最近的对话历史
3. **任务提取**：识别用户可能关心的主题和目标
4. **查询执行**：使用浏览器、文件读取、命令执行等工具获取相关信息
5. **响应生成**：生成友好且相关的主动帮助信息

#### 上下文感知

- 仅关注用户发起的消息，忽略系统消息
- 避免重复发送相同主题的主动提醒
- 优先处理高频和近期提到的主题

### 注意事项

1. **资源消耗**：启用后会定期分析上下文，可能增加计算资源使用
2. **干扰控制**：如果用户在收到主动消息后未回应，则不会连续发送新的主动消息
3. **模型依赖**：功能效果取决于所使用的AI模型能力，支持多媒体的模型能更好利用屏幕分析功能

### 典型应用场景

- 研究过程中的新信息获取
- 学习过程中的补充知识提供

---
