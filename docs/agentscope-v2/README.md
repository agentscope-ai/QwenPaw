# AgentScope v2 — Knowledge Base

Local, version-controlled reference for the **AgentScope v2** API, built by a team of
research agents from the official docs at <https://docs.agentscope.io/v2> (and the
`/api-reference/*` REST docs). This is the **single source of truth** the
[`agentscope-guardian`](../../.claude/skills/agentscope-guardian/SKILL.md) skill
consults before approving any change to qwenpaw or AgentScope code.

> ⚠️ **Version — verify first.** The user reported (2026-06-10) **updating the API to v2
> (agentscope 2.x)**. Do **not** assume it — check before any change:
> ```
> .venv/Scripts/python.exe -c "import agentscope; print(agentscope.__version__)"
> grep agentscope pyproject.toml
> ```
> At last check the venv still reported **`agentscope 1.0.20`** and `pyproject.toml` pinned
> `agentscope==1.0.20` (cf. commit *"restaurar APIs agentscope 1.x"*). If installed is **2.x**, this
> KB is the **direct** reference; if still **1.x**, a v2 doc signature is **not proof** the call works —
> prefer the installed lib + existing `src/qwenpaw/` usage and flag the mismatch. The guardian enforces
> this — see [`_guardian-checklist.md`](./_guardian-checklist.md) §0.

## How to use

- **Studying a concept** → open the matching file below.
- **Before editing qwenpaw/AgentScope code** → the guard hook blocks the edit until
  you run `/agentscope-guardian`, which reads the relevant file(s) here and the
  checklist, then APPROVES/REJECTS with the correct API.

## Index

### SDK — Building Blocks (`building-blocks/`)

| File | Covers | Key APIs |
|---|---|---|
| [agent.md](./building-blocks/agent.md) | The `Agent` engine: reply/stream, context compression, HITL, state | `Agent`, `Agent.reply`, `Agent.reply_stream`, `Agent.observe`, `Agent.compress_context`, `ContextConfig`, `AgentState`, `RedisStorage`, `ReActConfig` |
| [context.md](./building-blocks/context.md) | Context compression & offloading | `ContextConfig`, `Offloader`, `Offloader.offload_context/offload_tool_result`, `LocalWorkspace` |
| [message-and-event.md](./building-blocks/message-and-event.md) | `Msg` + content blocks + the full streaming `AgentEvent` taxonomy | `Msg`, `UserMsg`, `AssistantMsg`, `SystemMsg`, `append_event`, `TextBlock`, `ToolCallBlock`, `ToolResultBlock`, `*StartEvent/*DeltaEvent/*EndEvent` |
| [middleware.md](./building-blocks/middleware.md) | 6 onion hook positions + tool-source hook | `MiddlewareBase` (`on_reply`, `on_reasoning`, `on_acting`, `on_model_call`, `on_compress_context`, `on_system_prompt`, `list_tools`), `TracingMiddleware` |
| [model.md](./building-blocks/model.md) | Credential + ChatModel two-tier hierarchy, formatters, ModelCard | `*ChatModel` (OpenAI/Anthropic/DashScope/DeepSeek/Gemini/Moonshot/XAI/Ollama), `ChatModelBase`, `CredentialBase`, `*Formatter`, `ModelCard` |
| [permission-system.md](./building-blocks/permission-system.md) | ALLOW/DENY/ASK/PASSTHROUGH resolution for tool calls | `PermissionMode`, `PermissionBehavior`, `PermissionContext`, `PermissionRule`, `PermissionDecision` |
| [tool.md](./building-blocks/tool.md) | `ToolBase`, built-in tools, `Toolkit`, MCP, skills, tool groups | `ToolBase`, `Toolkit`, `Bash/Read/Write/Edit/Glob/Grep/Task*`, `FunctionTool`, `MCPTool`, `MCPClient`, `Stdio/HttpMCPConfig`, `reset_tools` |
| [workspace.md](./building-blocks/workspace.md) | Local/Docker/E2B execution environments + managers + MCP gateway | `WorkspaceBase`, `LocalWorkspace`, `DockerWorkspace`, `E2BWorkspace`, `*WorkspaceManager`, `GatewayMCPClient` |

### Core / Deploy (`./`)

| File | Covers |
|---|---|
| [overview.md](./overview.md) | Overview + quickstart (install, minimal Agent, streaming) — **flags the 1.0.20 vs 2.0 gap** |
| [deploy-agent-service.md](./deploy-agent-service.md) | FastAPI `create_app` hosting layer, REST surface, pluggable storage/bus/workspace backends |
| [deploy-agent-team.md](./deploy-agent-team.md) | Multi-agent layer: `TeamCreate`/`AgentCreate`/`TeamSay`/`TeamDelete`, `SubAgentTemplate` |
| [faq-and-changelog.md](./faq-and-changelog.md) | 1.0 → 2.0 breaking changes, module-by-module, all deprecations |

### REST API Reference (`api-reference/`)

| File | Endpoints |
|---|---|
| [agent.md](./api-reference/agent.md) | `POST/GET/PATCH/DELETE /agent`, `GET /agent/schema` |
| [sessions.md](./api-reference/sessions.md) | `POST/GET/PATCH/DELETE /sessions`, `/sessions/{id}/messages`, `/sessions/{id}/stream` (SSE) |
| [schedule.md](./api-reference/schedule.md) | `POST/GET/PATCH/DELETE /schedule`, `/schedule/{id}/sessions` |
| [credential.md](./api-reference/credential.md) | `POST/GET/PATCH/DELETE /credential`, `GET /credential/schemas` |
| [workspace.md](./api-reference/workspace.md) | `POST/GET/DELETE /workspace/mcp`, `/workspace/skill` |
| [chat-and-model.md](./api-reference/chat-and-model.md) | `POST /chat` (fire-and-forget + SSE), `GET /model` |

## Provenance

- Built by the `study-agentscope-v2` agent workflow (18 agents, one per doc unit).
- Each file lists its source URLs at the top. Re-run the workflow to refresh.
- Generated 2026-06-10 against docs.agentscope.io/v2; installed lib `agentscope 1.0.20`.
