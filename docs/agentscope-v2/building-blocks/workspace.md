# Workspace

> Source: https://docs.agentscope.io/v2/building-blocks/workspace.md

## Overview

A **workspace** is the agent's execution environment. It supplies the agent with three categories of resources:

1. **Tools** — built-in tools and MCPs.
2. **Skills** — reusable skill subdirectories (each with a `SKILL.md`).
3. **Context offloading** — for compressed messages and oversized tool results.

The workspace owns the lifecycle of the resources living inside it (MCP server processes, dynamically added skills, offloaded files).

AgentScope ships **three workspace implementations** — local filesystem, Docker container, and E2B cloud sandbox — plus a **workspace manager** that allocates and tracks workspaces in [Agent Service](https://docs.agentscope.io/v2/deploy/agent-service) so that multi-tenant deployments can map workspaces to users, agents, or sessions without rewriting the agent code.

For Docker and E2B, MCP servers run *inside* the isolated environment; the host reaches them through an in-workspace **MCP gateway** (see [MCP Gateway](#mcp-gateway)).

> Note on installed library: the installed package is `agentscope 1.0.20`; these docs are published under the `v2` documentation tree (`docs.agentscope.io/v2`).

---

## API Reference

### `WorkspaceBase` (abstract interface)

All three workspace implementations share the same `WorkspaceBase` interface, so the same agent code runs against any backend. The methods fall into four roles.

**Lifecycle (developer)**

| Method | Description |
| ------ | ----------- |
| `initialize()` | Provision the workspace (create directories/containers/sandboxes, mint gateway token, restore persisted MCP/skill state). Async. |
| `close()` | Release the workspace's resources. Async. Also drives the `async with` protocol. |
| `reset()` | Clear per-session state for pool reuse. Async. |

`initialize()` / `close()` also drive the `async with` protocol (async context manager).

**Discovery (agent)**

| Method | Returns | Description |
| ------ | ------- | ----------- |
| `list_tools()` | list of built-in tools | Enumerate the built-in tools. Async. |
| `list_mcps()` | list of active `MCPClient` instances | Enumerate active MCP clients (returns `MCPClient` instances regardless of backend; for Docker/E2B these are `GatewayMCPClient`). Async. |
| `list_skills()` | list of skills/loaders | Enumerate available skills. Async. |
| `get_instructions()` | str | A workspace-specific system prompt fragment. Async. |

**Offloading (agent)** — satisfies the `Offloader` protocol.

| Method | Signature | Description |
| ------ | --------- | ----------- |
| `offload_context` | `offload_context(session_id, msgs)` | Persist compressed context into `sessions/<session_id>/` and return a reference path the agent stores in place of the original payload. |
| `offload_tool_result` | `offload_tool_result(session_id, tool_result)` | Persist an oversized tool result into `sessions/<session_id>/` and return a reference path the agent stores in place of the original payload. |

**Dynamic management (user)** — changes are persisted to `.mcp` and `skills/` so they survive restarts.

| Method | Signature | Description |
| ------ | --------- | ----------- |
| `add_mcp` | `add_mcp(mcp_client)` | Register an MCP server at runtime; persisted to `.mcp`. |
| `remove_mcp` | `remove_mcp(name)` | Remove an MCP server by name; persisted to `.mcp`. |
| `add_skill` | `add_skill(skill_path)` | Add a skill at runtime; persisted under `skills/`. |
| `remove_skill` | `remove_skill(name)` | Remove a skill by name; persisted under `skills/`. |

---

### `LocalWorkspace`

Backend: **Host filesystem** (built-in tools run host-side).

Persists state directly under `workdir` on the host filesystem — restarts simply re-open the same directory.

**Constructor parameters (from example)**

| Parameter | Type | Default | Meaning |
| --------- | ---- | ------- | ------- |
| `workdir` | str (path) | — | Host directory where the workspace persists state. |
| `default_mcps` | list | `[]` | Seed-time MCP clients that populate a brand-new workspace on first `initialize()`. No-op on restart (state restored from `.mcp`). |
| `skill_paths` | list[str] | — | Seed-time skill paths populated on first `initialize()`. |

**Directory layout**

```
{workdir}/
├── .mcp           # registered MCP client configs (JSON array)
├── data/          # offloaded multimodal payloads (deduped by SHA-256)
├── skills/        # skill subdirectories, each with SKILL.md
│   └── .skills    # name/hash index for de-duplication
└── sessions/      # per-session context.jsonl and tool-result files
```

**Example**

```python
from agentscope.workspace import LocalWorkspace

workspace = LocalWorkspace(
    workdir="/data/my-workspace",
    default_mcps=[],
    skill_paths=["./skills/web-search"],
)
await workspace.initialize()
```

---

### `DockerWorkspace`

Backend: **Docker container** via `aiodocker`.

Bind-mounts the host `workdir` to `/workspace` inside the container, so the layout lives on the host and survives container restarts. **Omit `workdir`** for a purely ephemeral container whose writable layer disappears with it.

MCP servers run *inside* the container; the host reaches them through the MCP gateway.

**Constructor parameters (from example)**

| Parameter | Type | Default | Meaning |
| --------- | ---- | ------- | ------- |
| `base_image` | str | — | Container base image, e.g. `"python:3.11-slim"`. |
| `workdir` | str (path) | optional | Host directory bind-mounted to `/workspace` in the container. Omit for ephemeral container (state lost on stop). |
| `node_version` | str | — | Node.js version to install, e.g. `"20"`. |
| `extra_pip` | list[str] | — | Extra pip packages to install in the container, e.g. `["numpy", "pandas"]`. |
| `default_mcps` | list | `[]` | Seed-time MCP clients (no-op on restart). |
| `skill_paths` | list[str] | — | Seed-time skill paths. |

**Directory layout**

```
{workdir}/         # host directory, bind-mounted to /workspace in container
├── .mcp           # registered MCP client configs (JSON array)
├── data/          # offloaded multimodal payloads
├── skills/        # skill subdirectories, each with SKILL.md
└── sessions/      # per-session context.jsonl and tool-result files
```

**Example**

```python
from agentscope.workspace import DockerWorkspace

workspace = DockerWorkspace(
    base_image="python:3.11-slim",
    workdir="/data/docker-workspaces/agent-1",  # bind-mounted to /workspace
    node_version="20",
    extra_pip=["numpy", "pandas"],
    default_mcps=[],
    skill_paths=["./skills/web-search"],
)
await workspace.initialize()
```

---

### `E2BWorkspace`

Backend: **E2B cloud sandbox** via `AsyncSandbox`.

Uses the sandbox filesystem itself as the persistence layer — **there is no host `workdir`**. Each sandbox is tagged with `workspace_id` in its E2B metadata; on restart the manager looks it up via `AsyncSandbox.list(...)` and reconnects with `connect(sandbox_id=...)`. Pausing keeps disk state; resuming restores it intact.

MCP servers run *inside* the sandbox; the host reaches them through the MCP gateway.

**Constructor parameters (from example)**

| Parameter | Type | Default | Meaning |
| --------- | ---- | ------- | ------- |
| `template` | str | — | E2B sandbox template, e.g. `"base"`. |
| `api_key` | str | from `E2B_API_KEY` env | E2B API key. Can be supplied directly or via the `E2B_API_KEY` environment variable. |
| `timeout_seconds` | int | — | Sandbox timeout in seconds, e.g. `300`. |
| `default_mcps` | list | `[]` | Seed-time MCP clients (no-op on restart). |
| `skill_paths` | list[str] | — | Seed-time skill paths. |

**Directory layout**

```
$workdir/          # inside the sandbox
├── .mcp           # registered MCP client configs (JSON array)
├── data/          # offloaded multimodal payloads
├── skills/        # skill subdirectories, each with SKILL.md
└── sessions/      # per-session context.jsonl and tool-result files
```

**Example**

```python
from agentscope.workspace import E2BWorkspace

workspace = E2BWorkspace(
    template="base",
    api_key="your-e2b-api-key",   # or set E2B_API_KEY
    timeout_seconds=300,
    default_mcps=[],
    skill_paths=["./skills/web-search"],
)
await workspace.initialize()
```

---

### `WorkspaceManagerBase` (abstract)

A **workspace manager** is the allocator and lifecycle owner for workspaces in a multi-tenant service. Used by [Agent Service](https://docs.agentscope.io/v2/deploy/agent-service) to map incoming requests to the right workspace instance and release them on shutdown.

A manager is responsible for:

* **Allocation** — `create_workspace(user_id, agent_id, session_id)` builds a fresh workspace and tracks it; `get_workspace(..., workspace_id)` returns a live one or rebuilds on cache miss.
* **Caching and TTL** — workspaces are cached in memory keyed by `workspace_id`; idle entries are evicted after `ttl` seconds and their underlying resources (containers, sandboxes, MCP processes) torn down.
* **Isolation policy** — the manager decides whether two requests share a workspace; the built-in managers all isolate by `agent_id`, but `WorkspaceManagerBase` is a tiny abstract class that can be subclassed for per-user or per-session policies.
* **Cleanup** — `close(workspace_id)` evicts a single entry and `close_all()` drains the cache on app shutdown.

**Methods**

| Method | Signature | Description |
| ------ | --------- | ----------- |
| `create_workspace` | `create_workspace(user_id, agent_id, session_id)` | Build a fresh workspace and track it. Async. Returns a workspace instance (with `.workspace_id`). |
| `get_workspace` | `get_workspace(user_id, agent_id, session_id, workspace_id)` | Return a live cached workspace or rebuild on cache miss. Async. |
| `close` | `close(workspace_id)` | Evict a single cache entry and tear down its resources. Async. |
| `close_all` | `close_all()` | Drain the cache on app shutdown. Async. |

To plug a different isolation policy (per-user, per-session, or hybrid), subclass `WorkspaceManagerBase` and override `get_workspace` / `create_workspace` with your own keying.

---

### `LocalWorkspaceManager`

Pairs with `LocalWorkspace`. Isolation key: `agent_id` (workdir = `<basedir>/<agent_id>`). Cache key: `workspace_id`.

Import path (from example): `from agentscope.app._manager import LocalWorkspaceManager`

**Constructor parameters (from example)**

| Parameter | Type | Default | Meaning |
| --------- | ---- | ------- | ------- |
| `basedir` | str (path) | — | Base directory under which per-agent workdirs are created (`<basedir>/<agent_id>`). |
| `skill_paths` | list[str] | — | Seed skill paths applied to created workspaces. |
| `ttl` | float | — | Seconds before idle cached workspaces are evicted and torn down (e.g. `3600.0`). |

**Example**

```python
from agentscope.app._manager import LocalWorkspaceManager

manager = LocalWorkspaceManager(
    basedir="/data/workspaces",
    skill_paths=["./skills/coding"],
    ttl=3600.0,
)

ws = await manager.create_workspace(
    user_id="user-1",
    agent_id="agent-42",
    session_id="session-abc",
)

# Later, on a follow-up request for the same workspace:
ws = await manager.get_workspace(
    user_id="user-1",
    agent_id="agent-42",
    session_id="session-abc",
    workspace_id=ws.workspace_id,
)
```

---

### `DockerWorkspaceManager`

Pairs with `DockerWorkspace`. Isolation key: `(user_id, agent_id)` (workdir = `<basedir>/<user_id>/<agent_id>`). Cache key: `workspace_id`.

(Same `create_workspace` / `get_workspace` / `close` / `close_all` interface as `WorkspaceManagerBase`.)

---

### `E2BWorkspaceManager`

Pairs with `E2BWorkspace`. Isolation key: `agent_id` (workspace metadata, **no host workdir**). Cache key: `workspace_id`.

(Same `create_workspace` / `get_workspace` / `close` / `close_all` interface as `WorkspaceManagerBase`.)

---

### `GatewayMCPClient`

An `MCPClient` subclass used on the host for Docker/E2B backends. Its `connect` / `close` / `list_tools` calls become HTTP requests against the in-workspace MCP gateway, so the rest of the toolkit cannot tell it apart from a local MCP client.

### `GatewayMCPTool`

A `ToolBase` subclass whose `__call__` posts to `/mcps/{name}/tools/{tool}` and reconstructs the returned `ToolChunk`.

---

### MCP Gateway REST surface

`DockerWorkspace` and `E2BWorkspace` cannot register host-side MCP clients directly — the MCP servers live inside the container/sandbox, and stdio sessions cannot cross that boundary. AgentScope solves this with an **MCP gateway**: a lightweight FastAPI process that runs *inside* the workspace, owns the upstream MCP sessions, and exposes them over a single authenticated HTTP endpoint that the host talks to.

The gateway is protected by a **per-workspace bearer token minted at each `initialize()`**. The host talks to it over HTTPS with `Authorization: Bearer <token>`.

| Method + Path | Purpose |
| ------------- | ------- |
| `GET /health` | Health check. |
| `GET /mcps` | List registered MCP servers. |
| `POST /mcps` | Register an MCP server. |
| `DELETE /mcps` | Remove MCP server(s). |
| `GET /mcps/{name}/tools` | List tools exposed by a named MCP server. |
| `POST /mcps/{name}/tools/{tool}` | Invoke a specific tool on a named MCP server (used by `GatewayMCPTool.__call__`, returns a `ToolChunk`). |

Gateway topology:

```
Host:
  Agent → Toolkit → GatewayMCPClient (MCPClient subclass)
                         ↓ (HTTPS with Bearer token)
Container / E2B Sandbox:
  MCP Gateway (FastAPI) → MCP Server 1 (stdio)
                       → MCP Server 2 (http)
                       → MCP Server N
```

This abstraction keeps agent-side code identical across all three backends — a workspace returns `MCPClient` instances from `list_mcps()` regardless of whether the upstream session lives on the host (`LocalWorkspace`) or inside an isolated environment (`DockerWorkspace` / `E2BWorkspace`).

---

## Configuration

### Workspace backend selection

| Class | Backend | Persistence model |
| ----- | ------- | ----------------- |
| `LocalWorkspace` | Host filesystem (built-in tools run host-side) | State under `workdir`; restart re-opens directory. |
| `DockerWorkspace` | Docker container via `aiodocker` | `workdir` bind-mounted to `/workspace`; omit for ephemeral. |
| `E2BWorkspace` | E2B cloud sandbox via `AsyncSandbox` | Sandbox filesystem; tagged with `workspace_id`, reconnect via `connect(sandbox_id=...)`; pause/resume preserves disk. |

### Constructor options (combined)

| Option | Applies to | Type | Default | Controls |
| ------ | ---------- | ---- | ------- | -------- |
| `workdir` | Local, Docker | str path | — (Docker: optional) | Persistence directory. Docker omit = ephemeral. |
| `base_image` | Docker | str | — | Container base image. |
| `node_version` | Docker | str | — | Node.js version installed in container. |
| `extra_pip` | Docker | list[str] | — | Extra pip packages installed in container. |
| `template` | E2B | str | — | E2B sandbox template. |
| `api_key` | E2B | str | `E2B_API_KEY` env | E2B API key. |
| `timeout_seconds` | E2B | int | — | Sandbox timeout in seconds. |
| `default_mcps` | all | list | `[]` | Seed-time MCP clients (first `initialize()` only). |
| `skill_paths` | all | list[str] | — | Seed-time skill paths (first `initialize()` only). |

### Manager options

| Option | Applies to | Type | Controls |
| ------ | ---------- | ---- | -------- |
| `basedir` | Local, Docker | str path | Base directory for per-agent (Local) / per-user/per-agent (Docker) workdirs. |
| `skill_paths` | managers | list[str] | Seed skill paths applied to created workspaces. |
| `ttl` | managers | float (seconds) | Idle eviction timeout for cached workspaces. |

### Environment variables

| Variable | Used by | Purpose |
| -------- | ------- | ------- |
| `E2B_API_KEY` | `E2BWorkspace` | E2B API key (alternative to `api_key` argument). |

---

## Usage Patterns

### Integrate a workspace with an `Agent`

A workspace plugs into `Agent` along two axes — as a source of tools / MCPs / skills, and as the offloader for context compression.

```python
from agentscope.agent import Agent
from agentscope.tool import Toolkit
from agentscope.workspace import LocalWorkspace

workspace = LocalWorkspace(workdir="./my-workspace")
await workspace.initialize()

agent = Agent(
    name="coder",
    system_prompt="You are a coding assistant.",
    model=model,
    toolkit=Toolkit(
        tools=await workspace.list_tools(),
        mcps=await workspace.list_mcps(),
        skills_or_loaders=await workspace.list_skills(),
    ),
    offloader=workspace,
)
```

| Axis | Wiring | What the agent gets |
| ---- | ------ | ------------------- |
| Resources | `Toolkit(tools=..., mcps=..., skills_or_loaders=...)` | Built-in tools, MCP-provided tools, and skills available in the workspace. |
| Offloading | `Agent(offloader=workspace)` | On context-compression trigger or oversized tool result, the agent calls `workspace.offload_context()` / `offload_tool_result()` and stores the returned reference path in place of the original payload. |

`Agent` only depends on the `Offloader` protocol (`offload_context` / `offload_tool_result`), so any object satisfying that protocol can take the offloader role — the workspace is the typical implementation.

### Partition resources into `ToolGroup`s

Because the workspace exposes its resources as flat lists, you can partition them into `ToolGroup`s when the agent has too many tools to keep all active at once. Pass the groups to `Toolkit(tool_groups=[...])` and the agent activates them on demand through the built-in `ResetTools` meta-tool — only the reserved `basic` group stays always-on.

```python
from agentscope.tool import Toolkit, ToolGroup

mcps = await workspace.list_mcps()
skills = await workspace.list_skills()

toolkit = Toolkit(
    tools=await workspace.list_tools(),         # always active (basic group)
    tool_groups=[
        ToolGroup(name="search", description="Web search and retrieval.",
                  mcps=[m for m in mcps if m.name.startswith("search")]),
        ToolGroup(name="coding", description="Code editing skills.",
                  skills_or_loaders=skills),
    ],
)
```

### Allocate workspaces through a manager (multi-tenant)

```python
from agentscope.app._manager import LocalWorkspaceManager

manager = LocalWorkspaceManager(
    basedir="/data/workspaces",
    skill_paths=["./skills/coding"],
    ttl=3600.0,
)

ws = await manager.create_workspace(
    user_id="user-1",
    agent_id="agent-42",
    session_id="session-abc",
)

# Follow-up request for the same workspace:
ws = await manager.get_workspace(
    user_id="user-1",
    agent_id="agent-42",
    session_id="session-abc",
    workspace_id=ws.workspace_id,
)
```

In the agent service, the workspace manager is bound to the FastAPI app state during the lifespan and shared across all requests; routers acquire workspaces through the `get_workspace_manager` dependency injection.

---

## Gotchas & Version Notes

- **Seed inputs are first-`initialize()` only.** `default_mcps` and `skill_paths` are seed-time inputs — they populate a brand-new workspace on first `initialize()`. On restart the workspace restores its MCP list from the persisted `.mcp` file, so **re-passing the seeds is a no-op**. Do not rely on re-passing seeds to update an existing workspace; use `add_mcp` / `add_skill` instead.

- **Docker ephemeral vs persistent.** Omit `workdir` on `DockerWorkspace` for an ephemeral container whose writable layer (and all `.mcp`/`data`/`skills`/`sessions` state) disappears when it stops. Provide `workdir` (bind-mounted to `/workspace`) for state that survives restarts.

- **E2B has no host `workdir`.** `E2BWorkspace` does not take a `workdir`; persistence is the sandbox filesystem itself. The manager reconnects via `workspace_id` metadata (`AsyncSandbox.list(...)` + `connect(sandbox_id=...)`). Pause keeps disk; resume restores it.

- **MCP across isolation boundaries requires the gateway.** `DockerWorkspace` and `E2BWorkspace` **cannot** register host-side MCP clients directly — stdio sessions cannot cross the container/sandbox boundary. They use the in-workspace MCP gateway. From the host, always go through `GatewayMCPClient` / `GatewayMCPTool`; the toolkit treats them like any `MCPClient`. Do not attempt to attach a local stdio MCP client directly to a Docker/E2B workspace.

- **Gateway bearer token is per-`initialize()`.** The gateway's bearer token is minted at each `initialize()` — a stale token from a prior lifecycle will not authenticate. Always talk to the gateway with the current token.

- **`list_mcps()` returns `MCPClient` instances on all backends.** Agent-side code is backend-agnostic — never branch on backend type to handle MCP clients differently.

- **`basic` ToolGroup is always-on.** When partitioning into `ToolGroup`s, the reserved `basic` group stays always active; other groups are activated on demand via the built-in `ResetTools` meta-tool. Tools passed via `Toolkit(tools=...)` land in the always-active `basic` group.

- **Offloader protocol decoupling.** `Agent` depends only on the `Offloader` protocol (`offload_context` / `offload_tool_result`), not on `WorkspaceBase`. Any object implementing that protocol can be the offloader; the workspace is just the typical implementation.

- **Manager import path.** The example imports `LocalWorkspaceManager` from `agentscope.app._manager` (a private/underscored module path) — `from agentscope.app._manager import LocalWorkspaceManager`.

- **Isolation keys differ per manager.** `LocalWorkspaceManager` and `E2BWorkspaceManager` isolate by `agent_id`; `DockerWorkspaceManager` isolates by `(user_id, agent_id)`. All cache by `workspace_id`. Choose the manager/subclass to match the required isolation policy (per-user / per-session require subclassing `WorkspaceManagerBase`).

- **Local `data/` dedup is by SHA-256.** Offloaded multimodal payloads in `LocalWorkspace` `data/` are deduplicated by SHA-256; `skills/.skills` is a name/hash index for skill de-duplication.

- **Version note:** Documentation is under the `v2` tree (`docs.agentscope.io/v2`); installed package reported as `agentscope 1.0.20`. The page did not list explicit deprecated symbols or "use X instead of Y" renames beyond the seed-vs-runtime distinction above.
