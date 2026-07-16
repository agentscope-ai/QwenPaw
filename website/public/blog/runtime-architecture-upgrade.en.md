---
title: "QwenPaw Runtime Architecture Upgrade: Design, Implementation & Extensibility"
date: 2026-07-07
author: QwenPaw Team
tags: [ArchitectureUpgrade, EightPhaseOrchestration, HookSystem, QwenPaw2.0]
cover: /blog/runtime-architecture-upgrade-cover.png
excerpt: "QwenPaw Runtime was refactored from a 650-line god method into an 8-phase orchestration engine—enabling one-feature-one-directory extensibility with zero changes to Runtime core code."
---

# QwenPaw Runtime Architecture Upgrade: Design, Implementation & Extensibility

---

## Table of Contents

- 1. Background & Motivation — Why a Runtime Architecture Upgrade Was Needed
- 2. Overall Architecture
- 3. Runtime: The 8-Phase Orchestration Engine
- 4. Agent Building & Execution
- 5. Hook System — The Core Extensibility Mechanism
- 6. Prompt, Tool & Command Registration
- 7. Cross-Workspace Services: AppServiceManager
- 8. End-to-End Walkthrough: A Request's Complete Journey
- 9. Summary

---

## 1. Background & Motivation — Why a Runtime Architecture Upgrade Was Needed

### Core Pain Points

Before the Runtime architecture upgrade, QwenPaw's request handling was concentrated in a single `AgentRunner.query_handler()` method — a **god method exceeding 650 lines**. Every new feature (mission mode, coding mode, plan mode, cron isolation, skill injection, etc.) required **invasive modifications** to this core function, continuously adding if/else branches and cross-cutting state management.

A concrete example: adding a `/mission` feature at the time required changes across **8 files**, 2 of which were invasive modifications to core files. Each new feature added ~40 lines to runner.py. This development pattern created severe maintenance burden and merge conflicts.

Summary of specific pain points:

| #   | Pain Point                                   | Cost                                                                    |
| --- | -------------------------------------------- | ----------------------------------------------------------------------- |
| 1   | Runner is a god method                       | ~40 lines of runner.py changed per new feature                          |
| 2   | Agent construction hardcodes tool dictionary | Adding a tool requires ~80 lines of invasive changes to the agent class |
| 3   | System prompt assembly is scattered          | Injection points spread across mixin/runner/env                         |
| 4   | Three duplicate external interfaces          | Command dispatch + API + CLI, each method written 3 times               |
| 5   | New features require changes to 4–8 files    | /mission changed 8 files, 2 with core invasions                         |

### Goal

**One feature = one directory. Zero lines of change to the Runtime body.**

---

## 2. Overall Architecture

### Layered Design

The upgraded architecture adopts an OS-style layered design:

![Runtime Architecture Upgrade — Layered Design](https://img.alicdn.com/imgextra/i4/O1CN01wOJg0o1sEgaYyfFnW_!!6000000005735-55-tps-900-580.svg)

The actual structure implemented in code:

```
AppServiceManager (FastAPI lifespan scope, shared across workspaces)
│   ├── TaskTracker (cross-workspace task tracking)
│   ├── ToolCoordinator (cross-workspace tool lifecycle management)
│   └── ApprovalCoordinator (sub-agent approval)
│
└── Workspace (per-agent)
    ├── Runtime (execution engine: 8-phase orchestration)
    ├── ServiceManager (per-agent resource lifecycle)
    │   ├── MemoryManager / CronManager / ChatManager
    │   ├── DriverManager (MCP / Channel / ACP / A2A)
    │   └── SessionManager
    └── WorkspacePlugins (per-workspace registries)
        ├── HookRegistry (8-phase hook orchestration)
        ├── SlashCommandRegistry (unified command dispatch)
        ├── ToolRegistry (declarative tool registration)
        ├── PromptManager (pluggable prompt construction)
        └── modes: list[AgentMode] (behavior mode list)
```

### Core Responsibility Separation

| Layer                 | Lifecycle             | Responsibility                                                                      |
| --------------------- | --------------------- | ----------------------------------------------------------------------------------- |
| **AppServiceManager** | FastAPI lifespan      | Three coordinators shared across workspaces                                         |
| **Workspace**         | per-agent (dynamic)   | Single agent's resources + complete execution unit                                  |
| **Runtime**           | per-request           | Execution engine: 8-phase hook orchestration + build + execute                      |
| **ServiceManager**    | per-agent             | Manages per-agent resource start/stop, dependency ordering, parallel initialization |
| **WorkspacePlugins**  | Registered at startup | Hook / Command / Tool / Prompt / Mode registries                                    |

Strict contract: `AppServiceManager` has **exactly three** fields — `task_tracker`, `tool_coordinator`, `approval_coordinator`. The code enforces this via `__slots__`; adding any other field violates the contract. Per-workspace state belongs to `WorkspacePlugins` / `ServiceManager`.

Actual constraint in code:

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

## 3. Runtime: The 8-Phase Orchestration Engine

### Core: `Runtime.run()`

The previous pain point was that the runner was a god method. The solution is to split request processing into **8 fixed phases**, each serving as a hook mounting point.

The `Runtime` class (`src/qwenpaw/runtime/runtime.py`) is the per-workspace request orchestrator. Each request invokes `run()`, which produces SSE envelope objects through the 8-phase lifecycle.

```python
class Runtime:
    """Per-workspace request orchestrator.
    One ``Runtime`` instance per ``Workspace``.  ``run()`` is called once
    per ``AgentRequest`` and yields SSE envelope objects."""
```

### The 8 Phases

Defined in `src/qwenpaw/runtime/phases.py`:

```python
class Phase(str, Enum):
    PRE_DISPATCH = "pre_dispatch"       # Request normalization, before slash dispatch
    POST_DISPATCH = "post_dispatch"     # After slash dispatch finds no match
    PRE_AGENT_BUILD = "pre_agent_build" # Session loading and other pre-build preparation
    POST_AGENT_BUILD = "post_agent_build"  # Agent built; inject mode context
    PRE_EXECUTE = "pre_execute"         # Bootstrap / prompt refresh
    POST_RESPONSE = "post_response"     # Session save / cron writeback
    ON_ERROR = "on_error"               # Exception normalization
    FINALLY = "finally"                 # Idempotent cleanup
```

### Execution Flow

The actual execution flow of `Runtime.run()` interleaves **hook phases** with **fixed steps**:

![Runtime.run() — 8-Phase Orchestration Engine](https://img.alicdn.com/imgextra/i3/O1CN01iNpkJ11XDfmXuRxFO_!!6000000002890-55-tps-880-680.svg)

```
[Phase 1] PRE_DISPATCH hooks           ← Pluggable
[Fixed 1] SlashCommandRegistry.dispatch ← Fixed: unified command dispatch
[Phase 2] POST_DISPATCH hooks           ← Pluggable
[Phase 3] PRE_AGENT_BUILD hooks         ← Pluggable (session load, etc.)
[Fixed 2] AgentBuilder.build(ctx)       ← Fixed: build agent
[Phase 4] POST_AGENT_BUILD hooks        ← Pluggable
[Phase 5] PRE_EXECUTE hooks             ← Pluggable (bootstrap, etc.)
[Fixed 3] AgentExecutor.run(msgs)       ← Fixed: execute agent
[Phase 6] POST_RESPONSE hooks           ← Pluggable (session save, etc.)
[Phase 7] ON_ERROR hooks                ← Triggered on exception
[Phase 8] FINALLY hooks                 ← Always executed (cleanup)
```

Key design: **Phase positions are fixed; hooks registered at each phase are pluggable.** Adding a new feature = adding a new hook, no modification to `Runtime.run()` needed.

### Three Hook Actions

Each hook returns a `HookResult` containing one of three actions (`src/qwenpaw/runtime/hooks.py`):

```python
class HookAction(str, Enum):
    CONTINUE = "continue"           # Continue to next hook / phase
    SHORT_CIRCUIT = "short_circuit" # Return payload immediately, end current request
    SKIP_AGENT = "skip_agent"       # Skip agent build and execution, but subsequent hooks still run
```

For example, when a slash command is matched, `Runtime.run()` sets `skip_agent = True` — agent build and execution steps are skipped, but `POST_RESPONSE` and `FINALLY` hooks still execute, ensuring session persistence and cleanup.

---

## 4. Agent Building & Execution

The previous pain points were hardcoded tools in the agent class and scattered prompt assembly. The solution is declarative assembly via **AgentBuilder** and heartbeat-driven execution via **AgentExecutor**.

### AgentBuilder — Per-Request Agent Assembly

`AgentBuilder` (`src/qwenpaw/runtime/builder.py`) is responsible for constructing a complete `QwenPawAgent` for each request. It integrates:

| Component         | Source                                           | Description                                                                    |
| ----------------- | ------------------------------------------------ | ------------------------------------------------------------------------------ |
| **Toolkit**       | `local_workspace.list_tools()`                   | Internally uses `ToolRegistry` for declarative filtering by mode/skill/feature |
| **System Prompt** | `PromptManager.build_sync()`                     | Pluggable prompt contributors assembled by priority                            |
| **Model**         | `ProviderManager` + model factory                | LLM model + formatter                                                          |
| **Middlewares**   | `ToolCoordinatorMiddleware` + plugin middlewares | Onion-model middleware                                                         |
| **Governor**      | `ResourceGovernor`                               | Governance policy layer (sandbox, permissions)                                 |
| **Session State** | `ctx.session_state` (from `SessionLoadHook`)     | Session state restoration                                                      |

Key improvement: **Tools are no longer hardcoded in the agent class.** They are obtained via the workspace's `list_tools()`, which internally uses `ToolRegistry` (tools registered via the `@tool_descriptor` decorator) to filter per-request based on active modes, skills, and features.

### AgentExecutor & Envelope

`AgentExecutor` (`src/qwenpaw/runtime/executor.py`) drives the agent's reply stream and wraps a heartbeat mechanism — ensuring that during long idle periods (e.g., tool-guard approval waits), keep-alive envelopes are emitted instead of letting the SSE connection drop.

`Envelope` (`src/qwenpaw/runtime/envelope.py`) is an SSE state machine that translates agentscope `EventType` events into the frontend's streaming envelope protocol, tracking per-request state (text blocks, reasoning blocks, tool calls, data blocks) and producing the correct event sequence.

---

## 5. Hook System — The Core Extensibility Mechanism

This is the **core extensibility mechanism** of this architecture upgrade. Previously, adding a new feature required invasive changes to the runner; now you only need to register a hook.

![Hook System Class Hierarchy & Execution Mechanism](https://img.alicdn.com/imgextra/i2/O1CN01Xsmg2U1i3YoI1ACQN_!!6000000004357-55-tps-860-480.svg)

### Two Types of Hooks

The upgraded architecture provides two hook base classes for different scenarios:

| Base Class          | Definition Location | Execution Timing                    | Purpose                                                                 |
| ------------------- | ------------------- | ----------------------------------- | ----------------------------------------------------------------------- |
| **`LifecycleHook`** | `hooks/base.py`     | Every request reaching that phase   | Infrastructure: session load/save, bootstrap, skill env, error handling |
| **`ModeGatedHook`** | `modes/base.py`     | Only when the owning mode is active | Behavior modes: mission state, coding mode context, goal persistence    |

Both inherit from `HookBase` in `runtime/hooks.py`. `ModeGatedHook` automatically checks `self.owner_mode.is_active(ctx)` in `run()`, skipping execution if the condition is not met. This design eliminates a recurring bug in the old code: **every hook forgetting to add a mode activation check.**

### HookRegistry — Topological Sorting

`HookRegistry` (`src/qwenpaw/runtime/hooks.py`) manages hook registration and execution:

- Hooks are grouped by `Phase`
- Within the same phase, hooks are **topologically sorted** via `before` / `after` constraints, with priority as tiebreaker
- Cycle detection at startup throws `HookCycleError`
- Sort results are cached and automatically invalidated on new registration

```python
class HookBase:
    phase: Phase
    name: str
    priority: int = 100
    before: tuple[str, ...] = ()  # "run before these hooks"
    after: tuple[str, ...] = ()   # "run after these hooks"
```

For example, `SessionLoadHook` declares `priority = 10` (executes earlier in `PRE_AGENT_BUILD`), while `MissionStateLoadHook` declares `after = ("session_load",)`, ensuring task state loads after session state.

### Built-in LifecycleHooks

The project currently includes the following built-in LifecycleHooks (many appear as setup/cleanup pairs across different phases):

| Hook                       | Phase           | Priority | Responsibility                                                   |
| -------------------------- | --------------- | -------- | ---------------------------------------------------------------- |
| `ContextVarsSetupHook`     | PRE_DISPATCH    | 10       | Inject per-request ContextVars (workspace_dir, session_id, etc.) |
| `CronContextHook`          | PRE_DISPATCH    | 5        | Mark cron-originated requests                                    |
| `SessionLoadHook`          | PRE_AGENT_BUILD | 10       | Load session state from persistent storage                       |
| `MediaProcessHook`         | PRE_EXECUTE     | 5        | Process file/media blocks in input messages                      |
| `CronMemoryIsolateHook`    | PRE_EXECUTE     | 10       | Snapshot and clear agent context (cron isolation)                |
| `LangfuseTraceHook`        | PRE_EXECUTE     | 12       | Open Langfuse root trace span                                    |
| `BootstrapHook`            | PRE_EXECUTE     | 20       | Inject BOOTSTRAP.md guidance                                     |
| `SkillEnvHook`             | PRE_EXECUTE     | 40       | Push skill-declared environment variables                        |
| `CronMemoryRestoreHook`    | POST_RESPONSE   | 80       | Restore cron snapshot and append new messages                    |
| `SessionSaveHook`          | POST_RESPONSE   | 90       | Write back agent state to session storage                        |
| `ErrorNormalizeHook`       | ON_ERROR        | 10       | Normalize provider exceptions to user-readable messages          |
| `CancelCleanupHook`        | ON_ERROR        | 20       | Clean up approvals and interrupt agent on cancellation           |
| `SkillEnvCleanupHook`      | FINALLY         | 40       | Pop skill environment variable stack                             |
| `LangfuseTraceCleanupHook` | FINALLY         | 50       | Close Langfuse root trace span                                   |

A notable pattern: setup/cleanup hook pairs (e.g., `SkillEnvHook` in PRE_EXECUTE / `SkillEnvCleanupHook` in FINALLY) pass context manager handles between phases via the `ctx.extras` dictionary.

### AgentMode — Feature Bundle

`AgentMode` (`src/qwenpaw/modes/base.py`) is a **behavior bundle**: commands, tools, hooks, and prompt contributors packaged together.

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

`setup(workspace)` is the **sole entry point** for registration. "Which mode owns what" can be easily derived from the four content methods.

### WorkspacePlugins — Registry Container

All per-workspace registries reside in `WorkspacePlugins` (`src/qwenpaw/app/workspace/workspace_plugins.py`):

```python
@dataclass
class WorkspacePlugins:
    slash_command_registry: SlashCommandRegistry
    hook_registry: HookRegistry
    tool_registry: ToolRegistry
    prompt_manager: PromptManager
    modes: list[AgentMode]

    def register_mode(self, mode: AgentMode, workspace):
        # Actual code includes duplicate name detection; duplicate registration raises ValueError
        self.modes.append(mode)
        mode.setup(workspace)  # one call registers everything

    def active_mode_names(self, ctx) -> set[str]:
        return {m.name for m in self.modes if m.is_active(ctx)}
```

---

## 6. Prompt, Tool & Command Registration

### PromptManager — Composable System Prompt

Previously, system prompt construction was scattered across mixin, runner, and env modules; adding a new prompt fragment required finding the correct injection point. Now, `PromptManager` (`src/qwenpaw/runtime/prompt_manager.py`) declaratively assembles the system prompt from ordered `PromptContributor` instances:

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

The project includes 9 built-in contributors:

| Contributor                   | Priority | Content                                           |
| ----------------------------- | -------- | ------------------------------------------------- |
| `AgentIdentityContributor`    | 5        | Agent ID identity                                 |
| `AgentsMdContributor`         | 10       | AGENTS.md (including heartbeat / memory handling) |
| `SoulMdContributor`           | 20       | SOUL.md personality file                          |
| `ProfileMdContributor`        | 30       | PROFILE.md configuration file                     |
| `MultimodalHintContributor`   | 80       | Multimodal capability hints                       |
| `CodingModeContributor`       | 85       | Coding Mode personality block                     |
| `ScrollContextContributor`    | 86       | Scroll context strategy hints                     |
| `DriverPolicyHintContributor` | 88       | Driver policy guidance                            |
| `EnvContextContributor`       | 90       | Environment context (time / session / OS)         |

Adding a new prompt fragment = writing a `PromptContributor` and registering it. No changes to other files needed. Notably, `PromptManager.build()` includes built-in fault tolerance — if a single contributor throws an exception, it is logged and skipped without causing the entire prompt build to fail.

### ToolRegistry — Declarative Tool Registration

The previous pain point was that tools were hardcoded in the agent class; adding a tool required ~80 lines of invasive changes to the agent class. `ToolRegistry` (`src/qwenpaw/runtime/tool_registry.py`) replaces the old hardcoded tool dictionary with a declarative, filterable registry.

Each tool is described by a `ToolDescriptor` (core gating fields shown below; the full definition also includes `async_execution`, `description`, `metadata`, etc.):

```python
@dataclass(frozen=True)
class ToolDescriptor:
    name: str
    func: Callable
    enabled_by_default: bool = True
    requires_modes: tuple[str, ...] = ()    # Required active modes (any match)
    requires_skills: tuple[str, ...] = ()   # Required active skills (any match)
    requires_features: tuple[str, ...] = () # Required feature flags (all must match)
    requires_sandbox: tuple[str, ...] = ()  # Sandbox resource requirements
    # Also includes: async_execution, description, metadata, etc.
```

Built-in tools use the `@tool_descriptor` decorator for **automatic collection at import time**:

```python
@tool_descriptor(
    requires_modes=("goal",),
    description="Get the current goal status.",
)
async def get_goal(...):
    ...
```

At build time, `ToolRegistry.filter()` selects the correct tools based on the current request's mode, skill, and feature — no if/else needed.

### SlashCommandRegistry — Unified Command Dispatch

Previously, QwenPaw had **four parallel command mechanisms**: conversation, control, daemon, and skill, each method written 3 times. `SlashCommandRegistry` (`src/qwenpaw/runtime/slash_command_registry.py`) unifies them into a single dispatch point.

```python
@dataclass(frozen=True)
class CommandSpec:
    name: str
    handler: CommandHandler   # async (ctx, args) -> Msg | None
    aliases: tuple[str, ...]
    category: str             # "builtin" / "daemon" / "control" / "skill" / "user"
    help_text: str
```

### @api_action — Triple Auto-Generation

Addressing the previously listed pain point of "three duplicate external interfaces," `@api_action` (`src/qwenpaw/api_action.py`) fundamentally solves this problem: **one decorator simultaneously generates HTTP API, CLI subcommands, and slash commands**.

![@api_action — Triple Auto-Generation](https://img.alicdn.com/imgextra/i1/O1CN01WHSvAw1TncP49OphG_!!6000000002427-55-tps-820-410.svg)

Manager classes inherit from `ManagerBase` and mark methods with `@api_action`:

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

The triple generation implementation is distributed across three auto-registrars:

| Generation Path | Implementation File         | Mechanism                                                                                             |
| --------------- | --------------------------- | ----------------------------------------------------------------------------------------------------- |
| HTTP Route      | `app/_api_action_routes.py` | `register_http_routes()` scans `ManagerRegistry`, auto-mounts FastAPI endpoints                       |
| CLI Subcommand  | `cli/auto.py`               | `_LazyAutoGroup` lazy-loads; generated CLI commands call the server as HTTP clients                   |
| Slash Command   | `app/_api_action_routes.py` | `collect_slash_specs_from_api_actions()` generates `CommandSpec` registered to per-workspace registry |

Adding a new management interface = writing one `@api_action` method. Triple registration completes automatically, zero duplicate code.

---

## 7. Cross-Workspace Services: AppServiceManager

`AppServiceManager` holds **exactly three** cross-workspace coordinators, enforced via `__slots__` — adding any other field violates the contract. Per-workspace state belongs to `Workspace.plugins` / `Workspace.service_manager`.

### TaskTracker — Cross-Agent Session Tracking

`TaskTracker` tracks in-progress streaming requests across all workspaces. It supports graceful shutdown (waiting for active sessions to complete) and provides visibility into agents currently processing requests.

### ToolCoordinator — Tool Call Lifecycle

`ToolCoordinator` (`src/qwenpaw/tool_calls/`) provides **single tool call granularity** control. In the old system, `/stop` could only kill the entire agent. Now individual tool calls can be tracked, cancelled, or backgrounded.

Key components include `ToolCallEntry` (per-call state), `ToolCallStatus` (PENDING → RUNNING → DONE / CANCELLED state machine), `ToolCoordinatorMiddleware` (injected into agent middleware stack), `ToolResultPruningMiddleware` (tool result pruning), `ToolStream` (streaming tool output), `ToolCallContext` / `ToolHookRegistry` (HITL lifecycle hooks), etc.

### ApprovalCoordinator — Cross-Agent Approval

`ApprovalCoordinator` handles sub-agent approval chains. Because it resides in `AppServiceManager` (FastAPI lifespan scope), it naturally spans all workspaces — sub-agent approval requests are visible to the parent agent.

### ServiceManager — Per-Agent Resource Lifecycle

`ServiceManager` (`src/qwenpaw/app/workspace/service_manager.py`) manages per-agent services, supporting:

- **Declarative descriptors** — Each service has a `ServiceDescriptor` with priority, dependencies, start/stop methods
- **Priority-based parallel startup** — Same-priority services start concurrently
- **Reusable services** — Marked services survive workspace reload (e.g., MemoryManager)
- **Optional services** — Optional service failures are logged only, without aborting the workspace

```python
@dataclass
class ServiceDescriptor:
    name: str
    service_class: type | Callable[[Workspace], type]  # Supports dynamic class factory
    init_args: Callable[[Workspace], dict]
    post_init: Callable[[Workspace, Any], None]  # Optional post-creation hook
    start_method: str
    stop_method: str
    reusable: bool = False
    reload_func: Callable[[Workspace, Any], None]  # Reusable service reload callback
    dependencies: List[str] = []
    priority: int = 100
    concurrent_init: bool = True
    optional: bool = False
```

---

## 8. End-to-End Walkthrough: A Request's Complete Journey

Having introduced each module separately, we now tie them all together with a concrete scenario — watching a user message travel from entering the system to returning a response, seeing **what role each module plays**.

### Scenario: User Sends a Conversation Message in Mission Mode

Assume the user previously started a task via `/mission start "Deploy an ECS instance"`, and Mission Mode is now active. The user sends a follow-up message:

> "First, help me check what ECS specifications are currently available"

This message is **not** a slash command, so it follows the complete agent execution path. Here is its full journey through the system:

### Stop 1: Workspace Receives the Request

`Workspace` is the per-agent resource and execution unit. It holds `Runtime`, `ServiceManager`, and `WorkspacePlugins`.

Upon receiving the request, `Workspace` calls `Runtime.run()`, beginning the 8-phase orchestration.

### Stop 2: Runtime.run() — 8 Phases Executed Sequentially

**Phase 1 + Fixed 1 — Request Normalization & Command Dispatch**

LifecycleHooks inject per-request context variables (workspace_dir, session_id, etc.). Then `SlashCommandRegistry` attempts to match the user message — "First, help me check..." is not a slash command, so `skip_agent` remains `False`, continuing into the agent build flow.

**Phase 3 · PRE_AGENT_BUILD — ModeGatedHook + Topological Sorting in Action**

This demonstrates two core designs of the new architecture:

- `SessionLoadHook` (LifecycleHook) loads session state and conversation history first
- `MissionStateLoadHook` (**ModeGatedHook**, `after=("session_load",)`) then loads task state

Key point: `MissionStateLoadHook` declares `after=("session_load",)`, and HookRegistry's **topological sorting** ensures it always executes after SessionLoadHook. Meanwhile, because it is a ModeGatedHook, it is **automatically skipped** when Mission Mode is inactive — developers need not write any if/else.

**Fixed 2 · AgentBuilder — Three Registries Working Together**

`AgentBuilder` declaratively assembles the agent for this request: `ToolRegistry.filter()` filters the correct tool set based on currently active modes; `PromptManager.build_sync()` assembles the complete system prompt by priority; `ToolCoordinatorMiddleware` is injected to make every tool call trackable and cancellable.

→ Tools are not hardcoded, prompts are not hand-assembled — everything is declarative and filtered per-request.

**Phase 5 — Pre-Execution Preparation**

Multiple LifecycleHooks collaborate to prepare the environment: media processing, Langfuse trace opening, Bootstrap guidance injection, Skill environment variable pushing, etc.

**Fixed 3 · AgentExecutor — ToolCoordinator Cross-Layer Control**

The agent begins execution and decides to call `alicloud_cli` to query ECS specifications. This tool call passes through `ToolCoordinatorMiddleware`, creating a `ToolCallEntry` and tracking its status. If the user sends `/stop` at this point, `ToolCoordinator` (at the **AppServiceManager** layer) can precisely cancel **this one** tool call instead of killing the entire agent. `Envelope` translates output events into the SSE envelope protocol, and the heartbeat mechanism ensures the connection stays alive during long executions.

**Phase 6 + Phase 8 — Persistence & Cleanup**

After execution completes, `MissionStateSaveHook` (ModeGatedHook) saves task state, and `SessionSaveHook` writes back the session — symmetric with the load in Phase 3. Finally, the FINALLY phase **always executes** cleanup (environment variable stack pop, trace closing), regardless of whether the request succeeded or failed.

### Comparison: If the User Sends a Slash Command

If the user sends `/mission status` instead of a regular message:

1. **Phase 1** — Same as above, ContextVars injection
2. **Fixed 1** — `SlashCommandRegistry.dispatch()` matches the `mission` command → calls `_mission_handler` → returns status Msg → **`skip_agent = True`**
3. **Phase 2** — Command matched successfully, POST_DISPATCH branch **not entered**
4. **Phase 3 ~ Fixed 3** — Due to `skip_agent = True`, agent build and execution **are skipped**
5. **Phase 6** — `SessionSaveHook` **still executes**, ensuring state persistence
6. **Phase 8** — Cleanup hooks **still execute**

Key point: `skip_agent` skips Phase 3 ~ Fixed 3 (build and execution), but POST_RESPONSE and FINALLY phase hooks always execute. This is why the phase design is safer than a simple "early return" — cleanup and persistence are never missed.

### Comparison: Developer Wants to Add a New Mode

Suppose you are a developer wanting to add a new Mode to QwenPaw. You **do not need to modify a single line of Runtime code**.

Taking the existing `GoalMode` in the project as an example, its directory structure is:

```
modes/goal/
├── __init__.py      # Imports
├── goal_mode.py     # GoalMode(AgentMode) + setup()
├── tools.py         # Goal-specific tools: get_goal, create_goal, update_goal, etc.
└── contributor.py   # GoalPromptContributor(PromptContributor)
```

One call to `GoalMode.setup(workspace)` registers commands / tools / prompt into the `WorkspacePlugins` registries.

Worth noting: **Not every Mode needs to use all extension points.** The four content methods of AgentMode (`commands()`, `tools()`, `hooks()`, `prompt_contributors()`) are all optional:

- GoalMode uses **tools + prompt contributor**, no hooks — it controls iteration loops via `StopHandler`'s Gate mechanism (`GoalIterationGate`, `GoalBudgetGate`)
- MissionMode uses **command + hooks + prompt contributor**, managing task state load/save via `ModeGatedHook`
- Future new Modes can freely combine these extension points as needed

When GoalMode is active:

- `ToolRegistry` automatically filters tools with `requires_modes=("goal",)`
- `PromptManager` automatically includes GoalMode's prompt contributor
- Runtime code changes: **zero lines**

---

## 9. Summary

### Before vs. After Comparison

![Runtime Architecture Upgrade — Before vs. After](https://img.alicdn.com/imgextra/i3/O1CN016Acqyp24XG2MV1pk9_!!6000000007400-55-tps-880-490.svg)

| Aspect                        | Before                                      | After                                                    |
| ----------------------------- | ------------------------------------------- | -------------------------------------------------------- |
| Adding a mode                 | Modify runner.py ~40 lines + 3 wiring files | 1 directory, `setup()` registers once                    |
| Adding a tool                 | ~80 lines invasive change to agent class    | `@tool_descriptor` decorator                             |
| Adding a command              | Write 3 dispatch implementations            | 1 `CommandSpec`, or `@api_action` triple auto-generation |
| Adding a management interface | Write HTTP + CLI + slash 3 times            | One `@api_action` decoration, auto-generates all three   |
| Adding a prompt fragment      | Find insertion point in runner              | 1 `PromptContributor`                                    |
| Runtime code changes          | Every feature modifies runtime              | **Zero lines**                                           |

### What This Architecture Upgrade Achieved

1. **OS-style Layering** — `AppServiceManager` manages cross-workspace shared services; `Workspace` per-agent; `Runtime` per-request pure execution
2. **One Feature, One Module** — AgentMode bundles commands + tools + hooks + prompt; LifecycleHook handles cross-mode infrastructure
3. **Zero Runtime Invasion** — 8-phase hook mechanism for extension; Runtime has only three fixed steps (dispatch, build, execute)
4. **Declarative Agent Construction** — Tools via `ToolRegistry` + `@tool_descriptor`; Prompts via `PromptManager` + `PromptContributor`
5. **Unified Command Dispatch** — `SlashCommandRegistry` replaces four parallel mechanisms
6. **@api_action Triple Auto-Generation** — One decorator simultaneously generates HTTP API + CLI + slash command, completely eliminating interface duplication
7. **Single Tool Call Granularity Control** — `ToolCoordinator` supports tracking, cancellation, and backgrounding of individual tool calls
8. **Topologically Sorted Hooks** — `before` / `after` constraints + cycle detection, replacing fragile manual ordering
9. **Lightweight Isolation** — `ServiceManager` handles per-agent service lifecycle, supporting dependency-ordered startup and reusable services
