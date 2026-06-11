# FAQ & Changelog

> Source:
> - https://docs.agentscope.io/v2/others/faq.md
> - https://docs.agentscope.io/v2/change-log.md
>
> Installed library: agentscope 1.0.20. Docs site versions this as "v2" (AgentScope 2.0).

## Overview

This unit covers two documentation pages: the **FAQ** (high-level questions about
compatibility, sandboxing, frontend, language bindings) and the **Changelog**
(the authoritative, module-by-module list of breaking changes and new APIs
introduced in AgentScope 2.0 versus 1.0).

Key facts a reviewer must know:

- **AgentScope 2.0 is a hard breaking release.** It is NOT source-compatible with
  1.0 and there is **no automatic migration path**. New projects should target 2.0.
- The 1.0 docs remain available for existing users, but 2.0 redesigns the agent
  abstraction, adds an event system, and introduces the workspace and permission
  systems.
- Available in three languages, each its own repo: **Python**
  (`agentscope-ai/agentscope`), **TypeScript** (`agentscope-ai/agentscope-typescript`),
  **Java** (`agentscope-ai/agentscope-java`).
- A **TypeScript SDK** (`@agentscope-ai/agentscope`, installed via
  `pnpm install @agentscope-ai/agentscope`) mirrors the Python `Msg` and `Event`
  types for frontend consumption.
- A ready-made **Frontend UI** web app exists for the Agent Service.

These pages are prose/changelog notes rather than full API signature references —
the changelog enumerates names, renames, additions, and deprecations but generally
does NOT give full parameter signatures. Everything documented below is taken
directly from the two pages; where a full signature is not stated on the page, the
"Signature" field says "not specified on page" rather than inventing one.

## API Reference

> NOTE: The changelog names many classes/methods/fields but rarely gives complete
> signatures or parameter tables. Each entry below records exactly what the page
> states. Absence of a params table means the page provided no parameters.

### Agent (class)

- **Status:** Refactored. Replaces 1.0's `ReActAgent` with a new unified `Agent` class.
- **Signature:** not specified on page.
- **Behavior / methods:**
  - Replaces the 1.0 `__call__` method with the public methods `reply_stream` and `reply`.
  - `reply_stream` yields agent events for richer observability and control.
  - Supports **permission checks** and **human-in-the-loop** confirmations through the event stream.
  - Supports offloading compressed context and oversized tool results via the new `Offloader` interface.
- **Returns:** not specified on page (`reply_stream` yields agent events).

### reply (method on Agent)

- **Status:** New public method (replaces part of 1.0 `__call__`).
- **Signature:** not specified on page.

### reply_stream (method on Agent)

- **Status:** New public method (replaces part of 1.0 `__call__`).
- **Signature:** not specified on page.
- **Returns:** a stream that yields agent events.

### AgentState (type)

- **Status:** New. Explicit state management type replacing deprecated `state_dict` / `load_state_dict`.
- **Signature:** not specified on page.

### Offloader (interface / protocol)

- **Status:** New. Consumed by `Agent` for context compression and oversized tool-result handling.
- **Signature:** not specified on page (it is a protocol).

### Event system

- **Status:** New module (`<Badge>New</Badge>`).
- **Purpose:** Better frontend integration and human-in-the-loop support.
- Mirrored in the TypeScript SDK as the `Event` type.

### Msg (class)

- **Status:** Refactored.
- **Now inherits from:** Pydantic `BaseModel`, enforcing content validation.
- **New fields:** `created_at`, `finished_at`, `usage` (observability/accounting);
  also `content` field constraints tied to the specified `role` types.
- **New method:** `append_event(...)` — yields events from the agent's reply stream. Signature not specified on page.
- **Factory methods (new):** `UserMsg`, `AssistantMsg`, `SystemMsg` — create messages with the appropriate role.

### UserMsg / AssistantMsg / SystemMsg (factory methods)

- **Status:** New factory methods on `Msg` to create messages with the correct role.
- **Signature:** not specified on page.

### Content blocks (Pydantic BaseModel)

All content blocks now inherit from Pydantic `BaseModel` for validation,
serialization, and extensibility. All blocks gain an `id` field for traceability.

| Block | Status | Notes |
|---|---|---|
| `DataBlock` | New (unified) | Replaces `ImageBlock`, `AudioBlock`, `VideoBlock`; has a `media_type` field for extensibility |
| `ImageBlock` | Removed/merged | Consolidated into `DataBlock` |
| `AudioBlock` | Removed/merged | Consolidated into `DataBlock` |
| `VideoBlock` | Removed/merged | Consolidated into `DataBlock` |
| `HintBlock` | New | For agent guidance and intermediate reasoning |
| `ToolCallBlock` | Renamed | Was `ToolUseBlock` in 1.0; adds `state` and `suggested_rules` fields for tool-call lifecycle modeling |
| `ToolResultBlock` | Updated | Adds `state` field for tool-call lifecycle modeling |

### Permission system

- **Status:** New module (`<Badge>New</Badge>`).
- **Purpose:** Gating tool execution, human-in-the-loop confirmation, and overall agent autonomy control.
- **Signature:** not specified on page.

### ToolBase (abstraction)

- **Status:** New base abstraction for all tools.
- **Signature:** not specified on page.

### Built-in tools

Built-in tools refactored with **permission control**:

| Tool | Category | Notes |
|---|---|---|
| `Bash` | Filesystem/exec | Permission-controlled |
| `Edit` | Filesystem | Permission-controlled |
| `Glob` | Filesystem | Permission-controlled |
| `Grep` | Filesystem | Permission-controlled |
| `Read` | Filesystem | Permission-controlled |
| `Write` | Filesystem | Permission-controlled |
| `TaskCreate` | Task management | New |
| `TaskGet` | Task management | New |
| `TaskList` | Task management | New |
| `TaskUpdate` | Task management | New |

### Toolkit (class)

- **Status:** Refactored.
- **Behavior:** Supports tools, skills, MCPs, and tool groups as first-class citizens.
- **Related new types:**
  - `ToolGroup` — on-demand activation; the reserved `basic` group is always active.
  - `ResetTools` — a meta-tool letting the agent switch tool groups at runtime.
  - `MCPTool` — adapter for uniform tool registration.
  - `FunctionTool` — adapter for uniform tool registration.

### ToolGroup (class)

- **Status:** New. On-demand activation of grouped tools. Reserved group `basic` is always active.
- Skills can be packaged into `ToolGroup`s for on-demand activation.

### ResetTools (meta-tool)

- **Status:** New meta-tool for the agent to switch tool groups at runtime.

### MCPTool / FunctionTool (adapters)

- **Status:** New adapters for uniform tool registration into the `Toolkit`.

### MCPClient (class)

- **Status:** Refactored. MCP implementation collapsed into a single `MCPClient` class for a unified client surface.
- **Signature:** not specified on page.

### StdioMCPConfig (config type)

- **Status:** New declarative configuration type for typed (stdio) MCP setup.

### HttpMCPConfig (config type)

- **Status:** New declarative configuration type for typed (HTTP) MCP setup.

### Skill loaders

- **Status:** New module (`<Badge>New</Badge>`).
- Skill loader abstraction supports in-time skill loading from filesystem / sandbox / web.
- **`LocalSkillLoader` (class):** New. Supports directory-based skill loading and monitoring.
- Skills can be packaged into `ToolGroup`s.

### Workspace

- **Status:** New module (`<Badge>New</Badge>`).
- **Purpose:** Supplies tools, MCPs, skills, and context offloading through one unified interface.
- **Implementations (same agent-facing API, swappable backends):**
  - `LocalWorkspace` — host filesystem.
  - `DockerWorkspace` — container.
  - `E2BWorkspace` — E2B cloud sandbox.
- Workspaces own MCP server lifecycles, skill management, and context offloading.
- Includes an in-workspace **MCP gateway** so host-side agents can reach MCP servers running inside containers and sandboxes.

### Workspace managers (multi-tenant)

- `LocalWorkspaceManager` — New, with **agent-level isolation**.
- `DockerWorkspaceManager` — New, with **agent-level isolation**.
- `E2BWorkspaceManager` — New, with **agent-level isolation**.
- (FAQ also references a general `WorkspaceManager` for multi-tenant use; see `/v2/building-blocks/workspace`.)

### Model layer

- **Credential (module):** New. Credential management is **decoupled from the model classes** and centralized here. Supports credential-aware model listing and retrieval.
- **`ModelCard` (schema):** New. Describes model identity, capabilities, and parameter overrides.
- **`list_models` (class method):** New. For frontend model listing and selection.
- Formatter integrated into the chat model abstraction; default formatters supported per provider.
- **New provider support:** Kimi, Moonshot, DeepSeek, XAI, and OpenAI Response API.

### Middleware

- **Status:** New module (`<Badge>New</Badge>`). Refactors the 1.0 hook mechanism into a general agent middleware system.
- **`TracingMiddleware` (class):** New. The new entry point for OpenTelemetry tracing, replacing the in-agent integration.
- **`AGUIProtocolMiddleware` (class):** New (Agent Service). For streaming.
- **`ToolOffloadMiddleware` (class):** New (Agent Service). For oversized payloads.

### Agent Service

- **Status:** New module (`<Badge>New</Badge>`). FastAPI-based agent service + sandbox support, in the `app` module. See `/v2/deploy/agent-service`.

#### create_app (FastAPI factory)

- **Status:** New factory function.
- **Signature:** not specified on page.
- **Returns:** a FastAPI app exposing routers for: **agent, chat, model, credential, session, schedule, workspace, and background-task**.

#### Lifespan-scoped managers (Agent Service)

- `SessionManager` — New, lifespan-scoped, multi-tenant resource allocation.
- `SchedulerManager` — New, lifespan-scoped.
- `BackgroundTaskManager` — New, lifespan-scoped.
- Workspace managers (see above) — lifespan-scoped.
- **Redis-backed storage** added.

## Configuration

> The pages describe declarative config types and fields rather than a flat config
> file. Key configurable surfaces:

| Option / field / type | Belongs to | Controls |
|---|---|---|
| `media_type` (field) | `DataBlock` | Discriminates image/audio/video/other media in a unified block |
| `state` (field) | `ToolCallBlock`, `ToolResultBlock` | Tool-call lifecycle state |
| `suggested_rules` (field) | `ToolCallBlock` | Suggested permission rules for the tool call |
| `id` (field) | all content blocks | Traceability / referencing |
| `created_at`, `finished_at`, `usage` (fields) | `Msg` | Observability & accounting (timestamps, token usage) |
| `content` constraints (field) | `Msg` | Enforced per the specified `role` type |
| `role` | `Msg` factories (`UserMsg`/`AssistantMsg`/`SystemMsg`) | Message role |
| `StdioMCPConfig` (type) | MCP | Declarative stdio MCP server setup |
| `HttpMCPConfig` (type) | MCP | Declarative HTTP MCP server setup |
| `ModelCard` (schema) | Model | Model identity, capabilities, parameter overrides |
| `basic` tool group (reserved) | `Toolkit` / `ToolGroup` | Always-active tool group |
| Redis-backed storage | Agent Service | Persistence backend for the service |

(Per-field types, defaults, and full request/response body schemas are NOT given on
these two pages. A reviewer needing exact signatures must consult the dedicated
building-block pages, e.g. `/v2/building-blocks/workspace` and `/v2/deploy/agent-service`.)

## Usage Patterns

Concrete snippets present on the pages (verbatim):

**Install the TypeScript SDK:**
```bash
pnpm install @agentscope-ai/agentscope
```
It mirrors the Python `Msg` and `Event` types so frontend code can consume agent
streams without re-implementing the protocol.

**Language repositories:**
- Python — `https://github.com/agentscope-ai/agentscope`
- TypeScript — `https://github.com/agentscope-ai/agentscope-typescript`
- Java — `https://github.com/agentscope-ai/agentscope-java`

**Workspace backends (swap freely; same agent code):**
- `LocalWorkspace` (host filesystem)
- `DockerWorkspace` (container)
- `E2BWorkspace` (E2B cloud sandbox)

(No further runnable code examples appear on the FAQ or Changelog pages themselves.)

## Gotchas & Version Notes

Critical correct-usage rules for a guardian enforcing AgentScope 2.0 usage:

### Hard compatibility break
- **AgentScope 2.0 is NOT compatible with 1.0.** APIs are not source-compatible and
  there is **no automatic migration path**. Do not assume 1.0 code works.

### Agent API
- **Use `Agent`, not `ReActAgent`.** `ReActAgent` was refactored into the unified `Agent` class.
- **Do NOT call the agent via `__call__`.** Use `reply` or `reply_stream` instead.
  The agent is now a **pure producer** — the agent's `print` interface is **deprecated**.
- **Hooks are deprecated.** Use the new **agent middleware** system instead.
- **`state_dict` / `load_state_dict` are deprecated.** Use explicit state management
  via the `AgentState` type instead.
- **In-agent OpenTelemetry integration is deprecated.** Use `TracingMiddleware` instead.

### Messages / blocks
- **`Msg` now inherits from Pydantic `BaseModel`** and enforces content validation —
  invalid content will fail validation rather than silently pass.
- **`ToolUseBlock` is renamed to `ToolCallBlock`.** Use `ToolCallBlock`.
- **Do NOT use `ImageBlock` / `AudioBlock` / `VideoBlock`.** They are consolidated
  into the unified `DataBlock` with a `media_type` field.
- Prefer the factory methods `UserMsg` / `AssistantMsg` / `SystemMsg` to construct
  role-correct messages.

### Model layer
- **Credentials are decoupled from model classes** — manage them via the new
  `Credential` module, not on the model.
- **The `Trinity` model wrapper is deprecated.** Do not use it.

### MCP
- **Use the single `MCPClient` class** (unified surface) rather than the multiple
  1.0 MCP types. Configure declaratively with `StdioMCPConfig` / `HttpMCPConfig`.

### Tools / Toolkit
- Built-in tools (`Bash`, `Edit`, `Glob`, `Grep`, `Read`, `Write`, and the `Task*`
  tools) are **permission-controlled** — permission checks/human-in-the-loop are
  routed through the event stream and permission system.
- The `basic` tool group is reserved and always active; other groups activate
  on-demand and can be switched at runtime via the `ResetTools` meta-tool.

### Deprecated / removed / pending modules
- **Memory module is deprecated in 2.0** (due to tight coupling with agent logic).
  Do not rely on the 1.0 memory module.
- **RAG and long-term memory are unified into one module**, but the migration from
  1.0 is **in progress** — knowledge bases, document readers, and stores will return
  on the 2.0 architecture in **upcoming releases**. Do not assume they are available yet.
- (FAQ confirms RAG and long-term memory are being ported and "will land in upcoming
  releases" — track the changelog/GitHub releases.)

### Sandboxing
- Sandboxed execution is supported via the **workspace** abstraction
  (`LocalWorkspace` / `DockerWorkspace` / `E2BWorkspace`), all sharing one interface.
  Multi-tenant isolation is provided by the `*WorkspaceManager` classes with
  agent-level isolation.
