# CoPaw Daemon 与命令分叉设计（草案）

## 一、当前问题简述

- **分叉在 agent 内**：`/compact`、`/new` 等是否走「命令」是在 `CoPawAgent.reply()` 里用 `command_handler.is_command(query)` 判断的，只有请求已经进到 agent、且可能已经做了 session 加载之后才分叉。
- **后果**：所有请求都会先走到「创建 Agent + 加载 session」这条重路径，命令类请求也会创建完整 CoPawAgent、注册 MCP 等，成本高、语义上也不清晰（命令不应依赖 ReAct 与工具）。

目标：**在「进 agent 之前」就区分「系统/daemon 命令」与「普通对话」**，命令走轻量路径，不创建完整 Agent。

---

## 二、整体分叉策略（在 Runner 层叉开）

建议把分叉点放在 **Runner**（即 `AgentRunner.query_handler` 的入口），而不是 agent 的 `reply()`：

- **入口**：Channel/API → `runner.stream_query(request)` → runtime 会转成 `query_handler(msgs, request)`。
- **分叉位置**：在 `query_handler` 里，**在创建 `CoPawAgent` 之前**，根据「最后一条用户消息」判断类型并分流：
  - 若是 **系统命令**（现有 `/compact`、`/new`、`/clear` 等）或 **daemon 命令**（一阶段的 `/daemon ...`）→ 走 **命令管道**（见下），不创建 Agent，不跑 ReAct。
  - 否则 → 保持现有逻辑：创建 Agent、加载 session、`stream_printing_messages(agent(msgs))`。

这样「命令 vs 对话」的决策在 Runner 就完成，agent 只处理「已经是对话」的请求，符合「在其他地方就应该叉开」的目标。

**回复如何回到 channel？**  
分叉始终在 **Runner 内部**（`query_handler` 里）。命令路径执行完后，在 `query_handler` 里同样通过 `yield` 把事件流返回：`async for event in run_command_path(...): yield event`。这些 event 与「走 Agent」时一样，由 `stream_query` 的调用方（各 channel 或 /process API）消费，最终发回对应用户。因此**回复一定经过 runner 这一层**，channel 侧无需改协议，只是命令路径不创建 Agent、不跑 ReAct，但仍在同一套「runner → stream → channel」管道里回包。

---

## 三、命令分类与一阶段 Daemon

| 类型 | 示例 | 是否需要 session/记忆 | 执行位置 |
|------|------|------------------------|----------|
| 对话系统命令 | `/compact`, `/new`, `/clear`, `/history`, `/compact_str`, `/await_summary`, `/start` | 需要 memory/session | 命令管道（轻量） |
| Daemon 内置命令（一阶段） | `/daemon restart`, `/daemon status`, `/daemon reload_config` 等 | 不需要 session | 命令管道（daemon 子模块） |

**一阶段 daemon 内置命令建议**（按需裁剪）：

- **`/daemon restart`**（或 `restart_backend`）：通知进程管理器/父进程重启当前后端（例如发信号、或通过 sidecar 接口）；若当前是单进程，可先实现为「返回说明：请用 systemd/supervisor 重启」。
- **`/daemon status`**（或 `health`）：返回简要健康信息（进程 up、config 已加载、memory_manager 状态等），便于排查。
- **`/daemon reload_config`**：热加载配置（重新 `load_config()`，不重启进程）。
- **`/daemon version`** / **`/daemon info`**：版本、工作目录、关键路径等，方便 F12 自检。
- **`/daemon logs`**：**控制台日志**，输出最近终端/控制台上的日志（最近 N 行可配置）；in-chat 与 `copaw daemon logs` 共用执行层。

实现上：在「命令管道」里再按前缀分支到 **ConversationCommandHandlerMixin**（对话类命令）和 **DaemonCommandHandlerMixin**（daemon 类命令）；两者都**不**创建 CoPawAgent。两套逻辑做成 **两个 Mixin**，由 Runner 侧的「命令分发器」组合使用；同时 **copaw CLI** 增加 `copaw daemon` 子命令，CLI 直接调用 Daemon 的执行层（与 mixin 共用同一套逻辑），见下文。

---

## 三.1 两个 Mixin 与 CLI 统一执行

### 两个 Mixin

- **ConversationCommandHandlerMixin**（对话类命令）
  - 提供：`is_conversation_command(query) -> bool`、`async handle_conversation_command(query, memory, formatter, memory_manager, ...) -> Msg`。
  - 依赖：`agent_name`、`memory`、`formatter`、`memory_manager`（与现有 `CommandHandler` 一致）；不依赖 runner 实例。
  - 当前 `CommandHandler` 中的 `/compact`、`/new`、`/clear`、`/history`、`/compact_str`、`/await_summary`、`/start` 逻辑迁入此 mixin（或由 mixin 委托给一个纯函数/helper，便于单测）。

- **DaemonCommandHandlerMixin**（daemon 类命令）
  - 提供：`is_daemon_command(query) -> bool`、`async handle_daemon_command(query, context) -> Msg`（或返回结构化结果再由上层转 `Msg`）。
  - 依赖：通过 `context` 注入（如 `load_config`、`memory_manager`、可选 `signal_restart` 等），便于在 Runner 内传入真实依赖、在 CLI 内传入本地/空实现。
  - 解析 `/daemon <sub>`，子命令派发到同一套 **daemon 执行层**（见下）。

这样 Runner 侧的「命令分发器」可以组合两个 mixin（或一个组合类继承/持有两个 mixin），在 `query_handler` 里先判 `is_daemon_command`，再判 `is_conversation_command`，然后分别调用对应 `handle_*`。

### CLI：`copaw daemon` 与统一执行层

- 在 **copaw CLI** 中增加 **`daemon`** 子命令组，与现有 `cron`、`channels` 等平级，例如：
  - `copaw daemon status`
  - `copaw daemon restart`
  - `copaw daemon reload-config`
  - `copaw daemon version`
  - `copaw daemon logs`（输出最近控制台/终端日志，可选参数如 `-n` 行数）
- **执行层统一**：daemon 的「做什么」逻辑放在一层（例如 `daemon_commands.py` 里的函数或 DaemonCommandHandler 调用的 core），**两处调用**：
  1. **In-chat**：用户发 `/daemon status` 等 → Runner 命令管道 → **DaemonCommandHandlerMixin** → 调用同一执行层，返回内容转成 `Msg` 再转 Event 流。
  2. **CLI**：用户执行 `copaw daemon status` 等 → **daemon_cmd.py** 里对应 click 子命令 → 直接调用同一执行层，将结果打印到 stdout（或结构化输出）。
- CLI 调用时可能没有「运行中的 backend」（例如本机只装 CLI、后端在别的机器），因此执行层接口设计为可接受「可选依赖」：有 runner/内存管理器时返回更全的 status，无则仅返回本地可得到的信息（版本、工作目录、配置路径等）。

---

## 三.2 命令清单（待确认）

**说明**：本次修改**不涉及会话类命令集合的修改**，对话类保持现有实现与集合不变；仅新增/调整 daemon 类命令及 Runner 分叉与 mixin 设计。

### 对话类（ConversationCommandHandlerMixin）

**本次不修改**。仍为现有集合（设计上可迁入 mixin，命令列表与行为不变）：

| 命令 | 说明 | 是否需要等待 |
|------|------|--------------|
| `/start` | 同 `/new`，新会话欢迎 | 否 |
| `/compact` | 压缩当前对话并写摘要到长期记忆 | 是 |
| `/new` | 清空上下文并后台保存到长期记忆 | 否 |
| `/clear` | 清空上下文且不保存 | 否 |
| `/history` | 查看当前对话历史与 token 占用 | 否 |
| `/compact_str` | 查看当前压缩摘要内容 | 否 |
| `/await_summary` | 等待所有后台摘要任务完成 | 是 |

### Daemon 类（DaemonCommandHandlerMixin + `copaw daemon` CLI）

| 来源 | 命令 | 说明 |
|------|------|------|
| In-chat | `/daemon status` | 健康/状态（进程、config、memory_manager 等） |
| CLI | `copaw daemon status` | 同上，无 backend 时仅本地信息 |
| In-chat | `/daemon restart` | 请求重启（或返回「请用 systemd/supervisor 重启」说明） |
| CLI | `copaw daemon restart` | 同上或调用本地/远程重启接口 |
| In-chat | `/daemon reload-config` | 热加载配置 |
| CLI | `copaw daemon reload-config` | 同上（CLI 可请求远程 backend 执行） |
| In-chat | `/daemon version` | 版本、工作目录、关键路径 |
| CLI | `copaw daemon version` | 同上 |
| In-chat | `/daemon logs` | **控制台日志**：输出最近终端/控制台上的日志（最近 N 行，可配置） |
| CLI | `copaw daemon logs` | 同上，直接打印到 stdout |

---

## 四、命令管道（轻量路径，不创建 Agent）

目标：**只做「解析 → 执行命令 → 写回一条回复并 yield 成 stream」**，不启动 ReAct、不拉模型、不注册 MCP。

- **输入**：与现有一致，仍是 `request`（以及 runtime 解析好的 `msgs`）；从 `msgs` 取最后一条用户文本即可判断是否命令。
- **对话类命令**（需要 memory）：
  - 使用 **轻量上下文**：仅「session + memory + formatter + memory_manager」，不建 CoPawAgent。
  - 具体：从 `SafeJSONSession` 恢复出一个 **仅含 memory 的 state**（与现有 `load_session_state(agent=agent)` 里写 agent 的 memory 部分一致），必要时可抽一个 `load_session_state_to_memory(session_id, user_id, memory)` 或等价的最小接口；formatter 用现有的 `create_model_and_formatter()` 只取 formatter；memory_manager 用 runner 已有的 `self.memory_manager`。
  - 通过 **ConversationCommandHandlerMixin**（或组合了该 mixin 的 handler）执行 `handle_conversation_command(query, ...)`，得到一条 `Msg`。
  - 执行后 **写回 session**（只写 memory 相关 state），然后 **不**创建、不保存完整 agent。
- **Daemon 命令**（一阶段）：
  - 不加载 session，直接由 **DaemonCommandHandlerMixin** 根据子命令调用统一 **daemon 执行层**（与 CLI 共用）；context 由 runner 注入（`load_config`、`memory_manager` 等）。
- **输出**：将命令执行结果的那一条 `Msg` 转成与现有 stream 兼容的 **Event**，`async for` 只 yield 这一条（或先 start 再 complete 两个 event），这样 channel 侧无需改协议。

这样，**所有以 `/` 开头的命令都在 Runner 层被识别并走命令管道**；agent 的 `reply()` 里可以保留一次 `is_command` 作为兜底（例如直接调用 agent 的 API 时），但主路径上不会为命令创建 Agent。

---

## 五、二阶段：Daemon 具备 Agent 能力（F12 模式）

目标：daemon 不仅能执行内置命令，还能在「类似 Windows F12」的**不报错、可自检、可自愈**模式下跑一个轻量 agent。

- **定位**：
  - 用于 **运维/自检/故障恢复**：查日志、看配置、执行安全脚本、重试等。
  - **不替代主对话 agent**：主 agent 仍是现有 ReAct agent；daemon agent 是单独一条链路，专门做诊断与自愈。

- **F12 模式含义**：
  - **不把异常抛给用户**：所有未捕获异常在 daemon 内部捕获，返回结构化错误信息（如「步骤 X 失败：…，已记录日志」），并可选地触发自诊断。
  - **自我诊断**：失败时自动跑一轮「诊断步骤」（读最近日志、检查配置、检查依赖服务、磁盘等），结果写日志或作为下一轮上下文。
  - **自我修复**：在策略内允许的范围内自动重试、回退配置、重启子服务等；超出范围的给出明确建议（如「请执行 /daemon restart」）。
  - **自我进化**（中长期）：根据成功/失败结果更新策略或提示词（例如在 working_dir 下维护 `DAEMON_RULES.md` 或小型的「经验」存储），供下次诊断参考。

- **实现思路（对齐现有 ReAct agent）**：
  - 复用现有 **ReAct 流程**（与 `react_agent` 一致），但使用 **独立配置**：
    - 单独的 system prompt（如 `DAEMON_SOUL.md` / `daemon_system_prompt`），强调：只做诊断与安全操作、不修改业务数据、所有错误必须捕获并记录。
    - 可选：更小的 `max_iters`、只开放 **受限 tool 集**（如 `read_file`（仅限 log/config 路径）、`execute_shell_command`（白名单命令）、`get_current_time`，不开放写业务文件、不开放浏览器等）。
  - **执行层面**：
    - 在 daemon 的「执行循环」外再包一层 **try/except**：任何 step 或 tool 抛错 → 捕获 → 记录 → 可选地注入一条「系统错误」消息并让 agent 做一次「诊断与建议」的回复，再返回给用户（或仅写日志 + 返回简短摘要）。
  - **自我诊断**：
    - 工具层面：提供 `get_recent_logs`、`get_config_summary`、`check_health` 等只读/只检工具；或让 agent 通过现有 `read_file` + 白名单路径完成。
  - **自我进化**：
    - 二阶段可先做「把本次诊断结果与建议追加到某文件或结构化存储」；后续再做成「根据结果更新 prompt 或规则」的轻量策略，避免首版过于复杂。

这样，**二阶段 daemon 仍然在「命令管道」里叉开**：例如用户发 `/daemon diagnose` 或 `/daemon agent <自然语言>` 时，Runner 识别为 daemon 命令后，走「daemon agent 子路径」（创建 **DaemonAgent**，而不是主 CoPawAgent），用 F12 模式跑 ReAct，结果再通过同一套 stream 返回。

---

## 六、建议的代码结构（便于扩展）

- **`src/copaw/agents/command_handler.py`**（重构为 Mixin + 可选组合类）
  - **ConversationCommandHandlerMixin**：提供 `is_conversation_command`、`handle_conversation_command`；命令名集合 `SYSTEM_COMMANDS`（或 `CONVERSATION_COMMANDS`）保持在此。
  - 可选：保留 **CommandHandler** 作为默认组合类（仅继承该 mixin），供现有 CoPawAgent 兜底或测试使用。

- **`src/copaw/app/runner/daemon_commands.py`**（新建，一阶段）
  - **Daemon 执行层**：纯函数或小类，如 `run_daemon_status(context)`, `run_daemon_restart(context)`, `run_daemon_reload_config(context)`, `run_daemon_version(context)`, **`run_daemon_logs(context, lines=N)`**（对 **`WORKING_DIR / "copaw.log"`** 做 tail，最近 N 行）；供 mixin 与 CLI 共用。实现时需在 app 启动时为 copaw logger 增加写入 `copaw.log` 的 FileHandler。`context` 携带可选 `load_config`、`memory_manager`、`restart_callback`（单 worker 下可安排 `os._exit(0)`，多 worker 下可发 SIGHUP 到主进程 PID）等。
  - **DaemonCommandHandlerMixin**：提供 `is_daemon_command`、`handle_daemon_command`；解析 `/daemon <sub>` 后调用上述执行层，返回 `Msg` 或结构化结果。

- **`src/copaw/app/runner/command_dispatch.py`**（新建）
  - **入口**：`async def run_command_path(request, msgs, runner) -> AsyncIterator[Event]`。
  - 从 `msgs` 取最后一条用户文本；若 `DaemonCommandHandlerMixin.is_daemon_command(query)` 则走 daemon 分支，否则走 **ConversationCommandHandlerMixin** 分支。
  - 对话类：构造轻量 memory + formatter + memory_manager，加载 session，调用 mixin 的 `handle_conversation_command`，写回 session，将返回的 `Msg` 转为 Event 并 yield。
  - Daemon 类：runner 提供 context，调用 mixin 的 `handle_daemon_command`，将结果转 Event 并 yield。

- **`src/copaw/cli/daemon_cmd.py`**（新建）
  - **`daemon_group`**：`@click.group("daemon")`，注册子命令 `status`、`restart`、`reload-config`、`version`、**`logs`**（可选 `-n`/`--lines` 指定最近行数）。
  - 各子命令内部调用 **daemon_commands.py** 中的同一执行层（传入 CLI 用 context：如本地 `load_config`、`memory_manager=None`），将返回内容打印到 stdout。
  - 在 **`cli/main.py`** 中 `cli.add_command(daemon_group)`。

- **`src/copaw/app/runner/runner.py`**
  - 在 **query_handler** 最前面：
    - 从 `request`/`msgs` 解析出「最后一条用户消息」的纯文本；
    - 若为「系统命令或 daemon 命令」（例如以 `/` 开头且在允许列表内或为 `/daemon ...`），则：
      - `async for event in run_command_path(request, msgs, self): yield event`；
      - `return`（不再创建 Agent）。
  - 否则保持现有：创建 CoPawAgent、load_session、`stream_printing_messages(agent(msgs))`。

- **二阶段**：
  - **`src/copaw/agents/daemon_agent.py`**（或放在 `app/runner/` 下，视你是否希望与主 agent 平级）：
    - 基于现有 ReAct 的简化版 **DaemonAgent**：F12 包装（try/except + 诊断注入）、受限 tools、独立 system prompt。
  - 在 **command_dispatch** 或 **DaemonCommandHandlerMixin** 中：当子命令为 `diagnose` 或 `agent` 时，创建 DaemonAgent、跑一轮 ReAct、将结果转 Event 返回。

- **文档**：
  - 在现有 [commands 文档](https://copaw.agentscope.io/docs/commands) 中增加「命令分叉说明」和「Daemon 命令」小节；一阶段先列内置命令，二阶段再补「Daemon Agent（F12 模式）」说明。

---

## 七、小结与需要确认的点

- **分叉**：在 **Runner.query_handler** 入口根据「最后一条用户消息」判断命令 vs 对话，命令统一走 **命令管道**，不再在 agent 内分叉（agent 内可保留兜底）。
- **一阶段**：命令管道内实现 **Daemon 内置命令**（如 restart / status / reload_config / version），不创建 Agent；对话类命令用轻量 memory + 现有 CommandHandler 执行。
- **二阶段**：在命令管道内为 daemon 增加 **Agent 能力**（DaemonAgent + F12 模式）：只读/受限 tools、自诊断、自愈、错误不抛出、可选的自我进化。

**确认点**（已确认）：

1. **分叉位置**：同意放在 `query_handler` 入口，且命令路径完全不创建 CoPawAgent。
2. **两个 Mixin**：ConversationCommandHandlerMixin + DaemonCommandHandlerMixin，由命令分发器组合使用，采纳。
3. **CLI**：`copaw daemon status|restart|reload-config|version|logs` 与 in-chat `/daemon <sub>` 共用同一执行层，采纳。
4. **命令清单**：对话类本次不修改；daemon 类为 status / restart / reload-config / version / **logs** 共 5 个子命令，采纳。
5. **二阶段 F12**：同意「独立 DaemonAgent + 受限 tools + 外层 try/except + 自诊断/自愈」；自我进化首版只做「记录结果」。
6. **命名与路由**：对话命令保持 `/compact`、`/new` 等；daemon 支持短名（如 `/restart` 等价于 `/daemon restart`），同时保留 `/daemon <sub>` 形式，主要为日后 daemon agent 作为 query 预留。
