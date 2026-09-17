---
title: "QwenPaw Runtime 架构升级解析：架构、实现与扩展"
date: 2026-07-07
author: QwenPaw Team
tags: [架构升级, 八阶段编排, Hook机制, QwenPaw2.0]
cover: /blog/runtime-architecture-upgrade-cover.png
excerpt: "QwenPaw Runtime 从 650 行 god method 重构为 8 阶段编排引擎，通过 Hook、AgentMode 与声明式注册实现「一个功能一个目录、Runtime 零侵入扩展」。"
---

# QwenPaw Runtime 架构升级解析：架构、实现与扩展

---

## 目录

- 1. 背景与动机——为什么需要 Runtime 架构升级
- 2. 整体架构
- 3. Runtime：8 阶段编排引擎
- 4. Agent 构建与执行
- 5. Hook 系统——核心可扩展性机制
- 6. Prompt、Tool 与命令注册机制
- 7. 跨 Workspace 服务：AppServiceManager
- 8. 全链路实战：一个请求的完整旅程
- 9. 总结

---

## 1. 背景与动机——为什么需要 Runtime 架构升级

### 核心痛点

在 Runtime 架构升级之前，QwenPaw 的请求处理集中在一个 `AgentRunner.query_handler()` 方法中——这是一个超过 **650 行的 god method**。每个新功能（任务模式、编程模式、计划模式、定时任务隔离、Skill 注入……）都需要**侵入式修改**这个核心函数，不断增加 if/else 分支和交叉的状态管理。

一个具体的例子：当时要加一个 `/mission` 功能，需要改动 **8 个文件**，其中 2 个是核心文件的侵入式修改。每次新增功能，runner.py 都要多出 ~40 行。这样的开发模式带来了严重的维护负担和合并冲突。

具体痛点总结：

| #   | 痛点                       | 代价                                         |
| --- | -------------------------- | -------------------------------------------- |
| 1   | Runner 是 god method       | 每个新功能改动 ~40 行 runner.py              |
| 2   | Agent 构建硬编码 tool 字典 | 改 tool 必须侵入 agent 类 ~80 行             |
| 3   | System Prompt 拼接分散     | mixin/runner/env 多处注入                    |
| 4   | 对外接口三套重复           | 命令 dispatch + API + CLI，每个方法手写 3 遍 |
| 5   | 新增功能改 4-8 个文件      | /mission 改 8 文件，2 个核心侵入             |

### 目标

**一个功能 = 一个目录。Runtime 主体代码 = 零行改动。**

---

## 2. 整体架构

### 分层设计

升级后的架构采用了操作系统风格的分层架构：

![Runtime 架构升级 — 分层设计](https://img.alicdn.com/imgextra/i2/O1CN01GCwXyQ25Cw52JXziJ_!!6000000007491-55-tps-900-580.svg)

以下是代码中实际实现的结构：

```
AppServiceManager（FastAPI lifespan 级，跨 workspace 共享）
│   ├── TaskTracker（跨 workspace 任务追踪）
│   ├── ToolCoordinator（跨 workspace tool 生命周期管控）
│   └── ApprovalCoordinator（子 agent 审批）
│
└── Workspace (per-agent)
    ├── Runtime（执行引擎：8-phase orchestration）
    ├── ServiceManager（per-agent 资源生命周期）
    │   ├── MemoryManager / CronManager / ChatManager
    │   ├── DriverManager (MCP / Channel / ACP / A2A)
    │   └── SessionManager
    └── WorkspacePlugins（per-workspace 注册表）
        ├── HookRegistry（8 阶段 hook 编排）
        ├── SlashCommandRegistry（统一命令分发）
        ├── ToolRegistry（声明式 tool 注册）
        ├── PromptManager（可插拔 prompt 构建）
        └── modes: list[AgentMode]（行为模式列表）
```

### 核心职责分离

| 层级                  | 生命周期            | 职责                                              |
| --------------------- | ------------------- | ------------------------------------------------- |
| **AppServiceManager** | FastAPI lifespan    | 跨 workspace 共享的三个 coordinator               |
| **Workspace**         | per-agent (dynamic) | 单 agent 的资源 + 执行完整单元                    |
| **Runtime**           | per-request         | 执行引擎：8 阶段 hook 编排 + build + execute      |
| **ServiceManager**    | per-agent           | 管理 per-agent 资源的启停 / 依赖排序 / 并行初始化 |
| **WorkspacePlugins**  | 启动时注册          | Hook / Command / Tool / Prompt / Mode 注册表      |

严格契约：`AppServiceManager` **有且只有三个**字段——`task_tracker`、`tool_coordinator`、`approval_coordinator`。代码通过 `__slots__` 强制约束，添加任何其他字段都违反契约。Per-workspace 的状态属于 `WorkspacePlugins` / `ServiceManager`。

代码中的实际约束：

```python
# src/qwenpaw/app/app_services/app_service_manager.py

class AppServiceManager:
    __slots__ = (
        "task_tracker",
        "tool_coordinator",
        "approval_coordinator",
    )
```

---

## 3. Runtime：8 阶段编排引擎

### 核心：`Runtime.run()`

之前的痛点是 runner 是一个 god method。解决方案是把请求处理拆成 **8 个固定阶段**，每个阶段是 hook 的挂载点。

`Runtime` 类（`src/qwenpaw/runtime/runtime.py`）是 per-workspace 的请求编排器。每个请求调用 `run()`，通过 8 阶段生命周期产出 SSE 信封对象。

```python
class Runtime:
    """Per-workspace request orchestrator.
    One ``Runtime`` instance per ``Workspace``.  ``run()`` is called once
    per ``AgentRequest`` and yields SSE envelope objects."""
```

### 8 个阶段

定义在 `src/qwenpaw/runtime/phases.py` 中：

```python
class Phase(str, Enum):
    PRE_DISPATCH = "pre_dispatch"       # 请求规范化，slash 分发前
    POST_DISPATCH = "post_dispatch"     # slash 分发无匹配后
    PRE_AGENT_BUILD = "pre_agent_build" # session 加载等构建前准备
    POST_AGENT_BUILD = "post_agent_build"  # agent 已构建；注入模式上下文
    PRE_EXECUTE = "pre_execute"         # bootstrap / prompt 刷新
    POST_RESPONSE = "post_response"     # session 保存 / cron 写回
    ON_ERROR = "on_error"               # 异常规范化
    FINALLY = "finally"                 # 幂等清理
```

### 执行流程

`Runtime.run()` 的实际执行流程将 **hook 阶段**与**固定步骤**交替排列：

![Runtime.run() — 8 阶段编排引擎](https://img.alicdn.com/imgextra/i3/O1CN010lIWQm1HEYhAHk2iE_!!6000000000726-55-tps-880-680.svg)

```
[Phase 1] PRE_DISPATCH hooks           ← 可插拔
[Fixed 1] SlashCommandRegistry.dispatch ← 固定：统一命令分发
[Phase 2] POST_DISPATCH hooks           ← 可插拔
[Phase 3] PRE_AGENT_BUILD hooks         ← 可插拔（session load 等）
[Fixed 2] AgentBuilder.build(ctx)       ← 固定：构建 agent
[Phase 4] POST_AGENT_BUILD hooks        ← 可插拔
[Phase 5] PRE_EXECUTE hooks             ← 可插拔（bootstrap 等）
[Fixed 3] AgentExecutor.run(msgs)       ← 固定：执行 agent
[Phase 6] POST_RESPONSE hooks           ← 可插拔（session save 等）
[Phase 7] ON_ERROR hooks                ← 异常时触发
[Phase 8] FINALLY hooks                 ← 始终执行（清理）
```

关键设计：**阶段点位固定，注册在每个阶段的 hook 可插拔。** 新增功能 = 新增 hook，不需修改 `Runtime.run()`。

### 三种 Hook 动作

每个 hook 返回 `HookResult`，包含三种动作之一（`src/qwenpaw/runtime/hooks.py`）：

```python
class HookAction(str, Enum):
    CONTINUE = "continue"           # 继续执行下一个 hook / phase
    SHORT_CIRCUIT = "short_circuit" # 立即返回 payload，结束当前请求
    SKIP_AGENT = "skip_agent"       # 跳过 agent 构建和执行，但后续 hook 仍执行
```

例如，当匹配到 slash 命令时，`Runtime.run()` 设置 `skip_agent = True`——agent 构建和执行步骤被跳过，但 `POST_RESPONSE` 和 `FINALLY` hook 仍然执行，确保 session 持久化和清理。

---

## 4. Agent 构建与执行

之前的痛点是 tool 硬编码在 agent 类中、prompt 拼接分散。解决方案是通过 **AgentBuilder** 声明式组装和 **AgentExecutor** 心跳执行。

### AgentBuilder — 每个请求的 Agent 组装

`AgentBuilder`（`src/qwenpaw/runtime/builder.py`）负责为每个请求构建一个完整的 `QwenPawAgent`，它整合了：

| 组件              | 来源                                             | 描述                                                     |
| ----------------- | ------------------------------------------------ | -------------------------------------------------------- |
| **Toolkit**       | `local_workspace.list_tools()`                   | 内部使用 `ToolRegistry` 按 mode/skill/feature 声明式过滤 |
| **System Prompt** | `PromptManager.build_sync()`                     | 可插拔 prompt contributor 按优先级组装                   |
| **Model**         | `ProviderManager` + model factory                | LLM model + formatter                                    |
| **Middlewares**   | `ToolCoordinatorMiddleware` + plugin middlewares | 洋葱模型中间件                                           |
| **Governor**      | `ResourceGovernor`                               | 治理策略层（沙箱、权限）                                 |
| **Session State** | `ctx.session_state`（来自 `SessionLoadHook`）    | 会话状态恢复                                             |

关键改进：**tool 不再硬编码在 agent 类中。** 它们通过 workspace 的 `list_tools()` 获取，该方法内部使用 `ToolRegistry`（tool 通过 `@tool_descriptor` 装饰器注册）根据活跃的 mode、skill 和 feature 按请求过滤。

### AgentExecutor 与 Envelope

`AgentExecutor`（`src/qwenpaw/runtime/executor.py`）驱动 agent 的 reply stream，并包装心跳机制——确保在长时间空闲期间（如 tool-guard 审批等待），发出 keep-alive 信封而不是让 SSE 连接断开。

`Envelope`（`src/qwenpaw/runtime/envelope.py`）是 SSE 状态机，负责将 agentscope 的 `EventType` 事件翻译为前端的流式信封协议，跟踪每个请求的状态（文本块、推理块、工具调用、数据块）并产出正确的事件序列。

---

## 5. Hook 系统——核心可扩展性机制

这是本次架构升级的**核心可扩展性机制**。之前加一个新功能要侵入 runner，现在只需注册 hook。

![Hook 系统类层次与执行机制](https://img.alicdn.com/imgextra/i4/O1CN01VXIIew1dykBKWs1KF_!!6000000003805-55-tps-860-480.svg)

### 两类 Hook

升级后的架构提供两种 hook 基类，服务于不同场景：

| 基类                | 定义位置        | 执行时机             | 用途                                                              |
| ------------------- | --------------- | -------------------- | ----------------------------------------------------------------- |
| **`LifecycleHook`** | `hooks/base.py` | 每个到达该阶段的请求 | 基础设施：session load/save, bootstrap, skill env, error handling |
| **`ModeGatedHook`** | `modes/base.py` | 仅当所属 mode 激活时 | 行为模式：mission state, coding mode context, goal persistence    |

两者都继承自 `runtime/hooks.py` 中的 `HookBase`。`ModeGatedHook` 自动在 `run()` 中检查 `self.owner_mode.is_active(ctx)`，不满足则直接跳过。这个设计消除了旧代码中反复出现的 bug：**每个 hook 忘记添加 mode 激活检查。**

### HookRegistry — 拓扑排序

`HookRegistry`（`src/qwenpaw/runtime/hooks.py`）管理 hook 的注册和执行：

- Hook 按 `Phase` 分组
- 同一 phase 内，hook 通过 `before` / `after` 约束**拓扑排序**，priority 作为平局破除
- 启动时检测环路并抛出 `HookCycleError`
- 排序结果缓存，新注册时自动失效

```python
class HookBase:
    phase: Phase
    name: str
    priority: int = 100
    before: tuple[str, ...] = ()  # "run before these hooks"
    after: tuple[str, ...] = ()   # "run after these hooks"
```

例如，`SessionLoadHook` 声明 `priority = 10`（在 `PRE_AGENT_BUILD` 中较早执行），而 `MissionStateLoadHook` 声明 `after = ("session_load",)`，确保任务状态在会话状态之后加载。

### 内置 LifecycleHook

项目当前内置的 LifecycleHook 如下（许多以 setup/cleanup 成对出现，分布在不同阶段）：

| Hook                       | Phase           | Priority | 职责                                                         |
| -------------------------- | --------------- | -------- | ------------------------------------------------------------ |
| `ContextVarsSetupHook`     | PRE_DISPATCH    | 10       | 注入 per-request ContextVars（workspace_dir, session_id 等） |
| `CronContextHook`          | PRE_DISPATCH    | 5        | 标记 cron 来源请求                                           |
| `SessionLoadHook`          | PRE_AGENT_BUILD | 10       | 从持久化存储加载 session 状态                                |
| `MediaProcessHook`         | PRE_EXECUTE     | 5        | 处理输入消息中的文件/媒体块                                  |
| `CronMemoryIsolateHook`    | PRE_EXECUTE     | 10       | 快照并清空 agent 上下文（cron 隔离）                         |
| `LangfuseTraceHook`        | PRE_EXECUTE     | 12       | 开启 Langfuse root trace span                                |
| `BootstrapHook`            | PRE_EXECUTE     | 20       | 注入 BOOTSTRAP.md 引导信息                                   |
| `SkillEnvHook`             | PRE_EXECUTE     | 40       | 推入 skill 声明的环境变量                                    |
| `CronMemoryRestoreHook`    | POST_RESPONSE   | 80       | 恢复 cron 快照并追加新消息                                   |
| `SessionSaveHook`          | POST_RESPONSE   | 90       | 回写 agent 状态到 session 存储                               |
| `ErrorNormalizeHook`       | ON_ERROR        | 10       | Provider 异常规范化为用户可读消息                            |
| `CancelCleanupHook`        | ON_ERROR        | 20       | 取消时清理审批和中断 agent                                   |
| `SkillEnvCleanupHook`      | FINALLY         | 40       | 弹出 skill 环境变量栈                                        |
| `LangfuseTraceCleanupHook` | FINALLY         | 50       | 关闭 Langfuse root trace span                                |

一个值得注意的模式：setup/cleanup hook 对（如 `SkillEnvHook` 在 PRE_EXECUTE / `SkillEnvCleanupHook` 在 FINALLY）通过 `ctx.extras` 字典在阶段间传递上下文管理器句柄。

### AgentMode — 功能包

`AgentMode`（`src/qwenpaw/modes/base.py`）是一个**行为包**：命令、工具、hook 和 prompt contributor 打包在一起。

```python
class AgentMode:
    name: str

    def setup(self, workspace):
        for spec in self.commands():
            workspace.plugins.slash_command_registry.register(spec)
        for desc in self.tools():
            workspace.plugins.tool_registry.register(desc)
        for hook in self.hooks():
            workspace.plugins.hook_registry.register(hook)
        for contributor in self.prompt_contributors():
            workspace.plugins.prompt_manager.register(contributor)

    def commands(self) -> list[CommandSpec]: ...
    def tools(self) -> list[ToolDescriptor]: ...
    def hooks(self) -> list[HookBase]: ...
    def prompt_contributors(self) -> list[PromptContributor]: ...
    def is_active(self, ctx: HookContext) -> bool: ...
```

`setup(workspace)` 是注册的**唯一入口点**。"哪个 mode 拥有什么"可以从四个内容方法中轻松推导。

### WorkspacePlugins — 注册表容器

所有 per-workspace 的注册表都位于 `WorkspacePlugins`（`src/qwenpaw/app/workspace/workspace_plugins.py`）：

```python
@dataclass
class WorkspacePlugins:
    slash_command_registry: SlashCommandRegistry
    hook_registry: HookRegistry
    tool_registry: ToolRegistry
    prompt_manager: PromptManager
    modes: list[AgentMode]

    def register_mode(self, mode: AgentMode, workspace):
        # 实际代码含重复名称检测，重复注册会抛出 ValueError
        self.modes.append(mode)
        mode.setup(workspace)  # one call registers everything

    def active_mode_names(self, ctx) -> set[str]:
        return {m.name for m in self.modes if m.is_active(ctx)}
```

---

## 6. Prompt、Tool 与命令注册机制

### PromptManager — 可组合的 System Prompt

之前 system prompt 构建分散在 mixin、runner 和 env 模块中，新增一个 prompt 片段需要找到正确的注入点。现在，`PromptManager`（`src/qwenpaw/runtime/prompt_manager.py`）从有序的 `PromptContributor` 实例中声明式组装 system prompt：

```python
class PromptContributor:
    name: str
    priority: int = 100  # lower = appears earlier

    async def contribute(self, ctx) -> str | None:
        raise NotImplementedError

class PromptManager:
    async def build(self, ctx) -> str:
        parts = []
        for c in self._contributors:  # sorted by priority
            fragment = await c.contribute(ctx)
            if fragment:
                parts.append(fragment.strip())
        return "\n\n".join(parts)
```

项目内置 9 个 contributors：

| Contributor                   | Priority | Content                        |
| ----------------------------- | -------- | ------------------------------ |
| `AgentIdentityContributor`    | 5        | Agent ID 标识                  |
| `AgentsMdContributor`         | 10       | AGENTS.md（含心跳 / 记忆处理） |
| `SoulMdContributor`           | 20       | SOUL.md 人格文件               |
| `ProfileMdContributor`        | 30       | PROFILE.md 配置文件            |
| `MultimodalHintContributor`   | 80       | 多模态能力提示                 |
| `CodingModeContributor`       | 85       | Coding Mode 人格块             |
| `ScrollContextContributor`    | 86       | Scroll 上下文策略提示          |
| `DriverPolicyHintContributor` | 88       | Driver 策略指引                |
| `EnvContextContributor`       | 90       | 环境上下文（时间 / 会话 / OS） |

新增 prompt 片段 = 写一个 `PromptContributor` 并注册。不需改动其他文件。值得一提的是，`PromptManager.build()` 内置了容错机制——单个 contributor 抛异常会被记录日志并跳过，不会导致整个 prompt 构建失败。

### ToolRegistry — 声明式 Tool 注册

之前的痛点是 tool 硬编码在 agent 类中，每次加 tool 必须侵入 agent 类 ~80 行。`ToolRegistry`（`src/qwenpaw/runtime/tool_registry.py`）用声明式、可过滤的注册表替代了旧的硬编码 tool 字典。

每个 tool 由一个 `ToolDescriptor` 描述（以下为核心门控字段，完整定义还包含 `async_execution`、`description`、`metadata` 等）：

```python
@dataclass(frozen=True)
class ToolDescriptor:
    name: str
    func: Callable
    enabled_by_default: bool = True
    requires_modes: tuple[str, ...] = ()    # 需要的活跃 mode（任一匹配）
    requires_skills: tuple[str, ...] = ()   # 需要的活跃 skill（任一匹配）
    requires_features: tuple[str, ...] = () # 需要的 feature flag（全部匹配）
    requires_sandbox: tuple[str, ...] = ()  # 沙箱资源需求
    # 此外还有: async_execution, description, metadata 等字段
```

内置 tool 使用 `@tool_descriptor` 装饰器在 **import 时自动收集**：

```python
@tool_descriptor(
    requires_modes=("goal",),
    description="Get the current goal status.",
)
async def get_goal(...):
    ...
```

构建时，`ToolRegistry.filter()` 根据当前请求的 mode、skill 和 feature 选出正确的 tool——不需要 if/else。

### SlashCommandRegistry — 统一命令分发

之前 QwenPaw 有**四套并行命令机制**：conversation、control、daemon 和 skill，每个方法手写 3 遍。`SlashCommandRegistry`（`src/qwenpaw/runtime/slash_command_registry.py`）将它们统一为一个分发点。

```python
@dataclass(frozen=True)
class CommandSpec:
    name: str
    handler: CommandHandler   # async (ctx, args) -> Msg | None
    aliases: tuple[str, ...]
    category: str             # "builtin" / "daemon" / "control" / "skill" / "user"
    help_text: str
```

### @api_action — 三路自动生成

对于之前列出的痛点 "对外接口三套重复"，`@api_action`（`src/qwenpaw/api_action.py`）从根本上解决了这个问题：**一个装饰器，同时生成 HTTP API、CLI 子命令和 slash 命令**。

![@api_action — 三路自动生成](https://img.alicdn.com/imgextra/i3/O1CN01x6ttvV1ywYDU1zuDX_!!6000000006643-55-tps-820-410.svg)

Manager 类继承 `ManagerBase`，用 `@api_action` 标记方法即可：

```python
class CronManager(ManagerBase):
    endpoint_prefix = "crons"

    @api_action(
        methods={"http", "cli", "slash"},
        http_method="GET",
        http_path="/crons/jobs",
        slash_command="cron-list",
    )
    async def list_jobs(self) -> list[CronJobSpec]:
        return await self._repo.list_jobs()
```

三路生成的实现分布在三个自动注册器中：

| 生成路径   | 实现文件                    | 机制                                                                                      |
| ---------- | --------------------------- | ----------------------------------------------------------------------------------------- |
| HTTP Route | `app/_api_action_routes.py` | `register_http_routes()` 扫描 `ManagerRegistry`，自动挂载 FastAPI endpoint                |
| CLI 子命令 | `cli/auto.py`               | `_LazyAutoGroup` 延迟加载，生成的 CLI 命令作为 HTTP 客户端调用服务端                      |
| Slash 命令 | `app/_api_action_routes.py` | `collect_slash_specs_from_api_actions()` 生成 `CommandSpec` 注册到 per-workspace registry |

新增一个管理接口 = 写一个 `@api_action` 方法。三路注册自动完成，零重复代码。

---

## 7. 跨 Workspace 服务：AppServiceManager

`AppServiceManager` 持有**恰好三个**跨 workspace 的 coordinator，通过 `__slots__` 强制约束——添加任何其他字段都违反契约。Per-workspace 状态属于 `Workspace.plugins` / `Workspace.service_manager`。

### TaskTracker — 跨 Agent 会话追踪

`TaskTracker` 跨所有 workspace 追踪进行中的流式请求。它支持优雅关闭（等待活跃会话完成）并提供对当前处理请求的 agent 的可见性。

### ToolCoordinator — Tool 调用生命周期

`ToolCoordinator`（`src/qwenpaw/tool_calls/`）提供了**单 tool call 粒度**的控制。旧系统中 `/stop` 只能杀掉整个 agent。现在可以追踪、取消或后台化单个 tool 调用。

关键组件包括 `ToolCallEntry`（per-call 状态）、`ToolCallStatus`（PENDING → RUNNING → DONE / CANCELLED 状态机）、`ToolCoordinatorMiddleware`（注入 agent 中间件栈）、`ToolResultPruningMiddleware`（工具结果裁剪）、`ToolStream`（流式工具输出）、`ToolCallContext` / `ToolHookRegistry`（HITL 生命周期钩子）等。

### ApprovalCoordinator — 跨 Agent 审批

`ApprovalCoordinator` 处理子 agent 的审批链。因为它位于 `AppServiceManager`（FastAPI lifespan 级），天然跨所有 workspace——子 agent 的审批请求对父 agent 可见。

### ServiceManager — Per-Agent 资源生命周期

`ServiceManager`（`src/qwenpaw/app/workspace/service_manager.py`）管理 per-agent 服务，支持：

- **声明式描述符** — 每个服务有 `ServiceDescriptor`，包含优先级、依赖、start/stop 方法
- **基于优先级的并行启动** — 同优先级服务并发启动
- **可复用服务** — 标记的服务在 workspace reload 时存活（如 MemoryManager）
- **可选服务** — 可选服务失败只记日志，不中止 workspace

```python
@dataclass
class ServiceDescriptor:
    name: str
    service_class: type | Callable[[Workspace], type]  # 支持动态类工厂
    init_args: Callable[[Workspace], dict]
    post_init: Callable[[Workspace, Any], None]  # 创建后的可选钩子
    start_method: str
    stop_method: str
    reusable: bool = False
    reload_func: Callable[[Workspace, Any], None]  # 可复用服务 reload 回调
    dependencies: List[str] = []
    priority: int = 100
    concurrent_init: bool = True
    optional: bool = False
```

---

## 8. 全链路实战：一个请求的完整旅程

前面分别介绍了各个模块，现在我们用一个具体场景把它们全部串起来——看一条用户消息从进入系统到返回响应，**每个模块分别扮演了什么角色**。

### 场景：用户在 Mission Mode 下发送一条对话消息

假设用户之前已经通过 `/mission start "部署一个 ECS 实例"` 启动了一个任务，此时 Mission Mode 处于激活状态。用户现在发送了一条后续消息：

> "先帮我检查一下当前有哪些可用的 ECS 规格"

这条消息**不是** slash 命令，所以会走完整的 agent 执行路径。以下是它在系统中的完整旅程：

### 第一站：Workspace 接收请求

`Workspace` 是 per-agent 的资源和执行单元。它持有 `Runtime`、`ServiceManager` 和 `WorkspacePlugins`。

收到请求后，`Workspace` 调用 `Runtime.run()`，开始 8 阶段编排。

### 第二站：Runtime.run() — 8 阶段逐一执行

**Phase 1 + Fixed 1 — 请求规范化与命令分发**

LifecycleHook 注入 per-request 上下文变量（workspace_dir、session_id 等）。随后 `SlashCommandRegistry` 尝试匹配用户消息——"先帮我检查……" 不是 slash 命令，`skip_agent` 保持 `False`，继续进入 agent 构建流程。

**Phase 3 · PRE_AGENT_BUILD — ModeGatedHook + 拓扑排序实战**

这里体现了新架构的两个核心设计：

- `SessionLoadHook`（LifecycleHook）先加载 session 状态和对话历史
- `MissionStateLoadHook`（**ModeGatedHook**, `after=("session_load",)`）随后加载任务状态

关键点：`MissionStateLoadHook` 声明了 `after=("session_load",)`，HookRegistry 的**拓扑排序**确保它一定在 SessionLoadHook 之后执行。同时，因为它是 ModeGatedHook，Mission Mode 未激活时会被**自动跳过**——开发者无需写任何 if/else。

**Fixed 2 · AgentBuilder — 三个注册表联动**

`AgentBuilder` 为本次请求声明式组装 agent：`ToolRegistry.filter()` 根据当前激活的 mode 过滤出正确的 tool 集合；`PromptManager.build_sync()` 按优先级拼装完整 system prompt；同时注入 `ToolCoordinatorMiddleware` 使每个 tool call 可被追踪和取消。

→ Tool 不是硬编码的，prompt 不是手拼的——全部声明式、按请求过滤。

**Phase 5 — 执行前准备**

多个 LifecycleHook 协同完成环境准备：媒体处理、Langfuse trace 开启、Bootstrap 引导信息注入、Skill 环境变量推入等。

**Fixed 3 · AgentExecutor — ToolCoordinator 跨层控制**

Agent 开始执行，决定调用 `alicloud_cli` 查询 ECS 规格。这个 tool call 经过 `ToolCoordinatorMiddleware`，创建 `ToolCallEntry` 并追踪其状态。如果此时用户发送 `/stop`，`ToolCoordinator`（位于 **AppServiceManager** 层）可以精确取消**这一个** tool call，而不是杀掉整个 agent。`Envelope` 将产出事件翻译为 SSE 信封协议，心跳机制确保长时间执行期间连接不断开。

**Phase 6 + Phase 8 — 持久化与清理**

执行完成后，`MissionStateSaveHook`（ModeGatedHook）保存任务状态，`SessionSaveHook` 回写 session——与 Phase 3 的 load 形成对称。最后 FINALLY 阶段**始终执行**清理工作（环境变量弹栈、trace 关闭），无论请求成功还是失败。

### 对比：如果用户发送的是 Slash 命令

如果用户发送的是 `/mission status` 而非普通消息：

1. **Phase 1** — 同上，ContextVars 注入
2. **Fixed 1** — `SlashCommandRegistry.dispatch()` 匹配到 `mission` 命令 → 调用 `_mission_handler` → 返回状态信息 Msg → **`skip_agent = True`**
3. **Phase 2** — 命令已匹配成功，POST_DISPATCH 分支**不会进入**
4. **Phase 3 ~ Fixed 3** — 因 `skip_agent = True`，agent 构建和执行**被跳过**
5. **Phase 6** — `SessionSaveHook` **仍然执行**，确保状态持久化
6. **Phase 8** — 清理 hook **仍然执行**

关键点：`skip_agent` 跳过的是 Phase 3 ~ Fixed 3（构建和执行），但 POST_RESPONSE 和 FINALLY 阶段的 hook 始终执行。这就是为什么 phase 设计比简单的 "提前返回" 更安全——不会遗漏清理和持久化。

### 对比：开发者想新增一个 Mode

假设你是一个开发者，想在 QwenPaw 中新增一个 Mode。你**不需要修改 Runtime 任何一行代码**。

以项目中已有的 `GoalMode` 为例，它的目录结构为：

```
modes/goal/
├── __init__.py      # 导入
├── goal_mode.py     # GoalMode(AgentMode) + setup()
├── tools.py         # get_goal, create_goal, update_goal 等 goal 专属 tool
└── contributor.py   # GoalPromptContributor(PromptContributor)
```

`GoalMode.setup(workspace)` 一次调用，commands / tools / prompt 全部注册到 `WorkspacePlugins` 的注册表中。

这里值得注意：**不是每个 Mode 都需要用到全部扩展点**。AgentMode 的四个内容方法（`commands()`、`tools()`、`hooks()`、`prompt_contributors()`）都是可选的：

- GoalMode 使用了 **tools + prompt contributor**，没有 hooks——它通过 `StopHandler` 的 Gate 机制（`GoalIterationGate`、`GoalBudgetGate`）来控制迭代循环
- MissionMode 使用了 **command + hooks + prompt contributor**，通过 `ModeGatedHook` 管理任务状态加载/保存
- 未来新增的 Mode 可以根据需要自由组合这些扩展点

当 GoalMode 激活时：

- `ToolRegistry` 自动过滤出带 `requires_modes=("goal",)` 的 tool
- `PromptManager` 自动包含 GoalMode 的 prompt contributor
- Runtime 代码改动：**零行**

---

## 9. 总结

### 前后对比

![Runtime 架构升级 — 前后对比](https://img.alicdn.com/imgextra/i2/O1CN01Kn2W5Q1IOSsT9NjnF_!!6000000000883-55-tps-880-490.svg)

| 方面             | 之前                                 | 之后                                              |
| ---------------- | ------------------------------------ | ------------------------------------------------- |
| 新增 mode        | 修改 runner.py ~40 行 + 3 个接线文件 | 1 个目录，`setup()` 一次注册                      |
| 新增 tool        | 侵入 agent 类 ~80 行                 | `@tool_descriptor` 装饰器                         |
| 新增命令         | 3 套 dispatch 各写一遍               | 1 个 `CommandSpec`，或 `@api_action` 三路自动生成 |
| 新增管理接口     | HTTP + CLI + slash 手写 3 遍         | `@api_action` 装饰一次，自动生成三路              |
| 新增 prompt 片段 | 在 runner 中找位置插入               | 1 个 `PromptContributor`                          |
| Runtime 代码改动 | 每个功能都修改 runtime               | **零行**                                          |

### 本次架构升级达成了什么

1. **OS 式分层** — `AppServiceManager` 管理跨 workspace 共享服务；`Workspace` per-agent；`Runtime` per-request 纯执行
2. **一个功能一个模块** — AgentMode 打包 commands + tools + hooks + prompt；LifecycleHook 处理跨 mode 基础设施
3. **Runtime 零侵入** — 8 阶段 hook 机制扩展；Runtime 仅三个固定步骤（dispatch, build, execute）
4. **声明式 Agent 构建** — Tool 通过 `ToolRegistry` + `@tool_descriptor`；Prompt 通过 `PromptManager` + `PromptContributor`
5. **统一命令分发** — `SlashCommandRegistry` 替代四套并行机制
6. **@api_action 三路自动生成** — 一个装饰器同时生成 HTTP API + CLI + slash command，彻底消除接口重复
7. **单 Tool Call 粒度控制** — `ToolCoordinator` 支持单个 tool call 的追踪、取消和后台化
8. **拓扑排序 Hook** — `before` / `after` 约束 + 环路检测，替代脆弱的手动排序
9. **轻量隔离** — `ServiceManager` 处理 per-agent 服务生命周期，支持依赖排序启动和可复用服务
