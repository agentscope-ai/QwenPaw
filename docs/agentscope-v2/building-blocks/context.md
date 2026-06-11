# Context

> Source: https://docs.agentscope.io/v2/building-blocks/context.md

## Overview

The **context** functions as an agent's working memory — it contains the messages that the LLM processes during each reasoning step. AgentScope prevents context overflow through **three mechanisms**:

1. **Context compression** — summarizing older messages.
2. **Tool result truncation** — capping oversized tool outputs.
3. **Context offloading** — persisting removed content externally.

The **Model API Input** comprises three layers:

- **System Prompt** — base prompt + skill instructions + middleware transforms.
- **Summary** — compressed history (only present when compression has occurred).
- **Context** — recent, uncompressed messages.

The two related subsystems documented here are **Compact Context** (compression + truncation, configured via `ContextConfig`) and **Offload Context** (the `Offloader` protocol, `LocalWorkspace`, and custom offloaders).

---

## API Reference

### ContextConfig

A configuration object passed to an `Agent` at construction time (parameter `context_config`) to control context compression and tool-result truncation behavior.

**Import:**

```python
from agentscope.agent import Agent, ContextConfig
```

**Usage at construction:**

```python
from agentscope.agent import Agent, ContextConfig

agent = Agent(
    name="my_agent",
    system_prompt="...",
    model=model,
    toolkit=toolkit,
    context_config=ContextConfig(
        trigger_ratio=0.8,
        reserve_ratio=0.1,
        tool_result_limit=3000,
    ),
)
```

**Parameters:**

| Parameter | Type | Default | Meaning |
|-----------|------|---------|---------|
| `trigger_ratio` | `float` | (not stated; example uses `0.8`) | Activates compression when token usage exceeds this ratio of the model context size. **Max value: `0.9`.** |
| `reserve_ratio` | `float` | (not stated; example uses `0.1`) | Proportion of context tokens retained as recent messages after compression. |
| `tool_result_limit` | `int` | (not stated; example uses `3000`) | Maximum tokens per tool result; outputs exceeding this are truncated. |
| `compression_prompt` | `str` | (not stated) | Guides the model's summary generation. |
| `summary_template` | `str` | (not stated) | Formats the summary into the context. |
| `summary_schema` | `dict` | (not stated) | JSON Schema constraining the structured summary output. |

> Note: The docs page only lists `trigger_ratio`, `reserve_ratio`, and `tool_result_limit` with example values; the remaining three fields (`compression_prompt`, `summary_template`, `summary_schema`) are listed in the parameter table without default values.

---

### Agent.compress_context()

Manually triggers context compression. Compression also runs **automatically** before each reasoning step (see Usage Patterns); this method lets you force it on demand and optionally override the agent's configured `ContextConfig` for a single call.

**Signature (inferred from documented usage):**

```python
async def compress_context(
    self,
    context_config: ContextConfig | None = None,
) -> None
```

**Parameters:**

| Parameter | Type | Default | Meaning |
|-----------|------|---------|---------|
| `context_config` | `ContextConfig` | the agent's default config | Override config applied to this single compression call only. |

**Returns:** awaitable (`None` documented; method is `async` and must be awaited).

**Examples:**

```python
# Using agent's default config
await agent.compress_context()

# Override config for single call
await agent.compress_context(
    context_config=ContextConfig(trigger_ratio=0.5, reserve_ratio=0.1),
)
```

---

### Offloader (protocol)

A protocol that defines how compressed messages and truncated tool results are persisted to external storage. Attach an implementation to an `Agent` via the `offloader` parameter.

**Methods:**

| Method | Signature | Description |
|--------|-----------|-------------|
| `offload_context` | `offload_context(session_id, msgs)` | Persists compressed messages; returns a reference (e.g. a path or URI). |
| `offload_tool_result` | `offload_tool_result(session_id, tool_result)` | Persists a truncated tool result; returns a reference. |

**Full async signatures (from the custom-offloader example):**

```python
async def offload_context(
    self,
    session_id: str,
    msgs: list[Msg],
    **kwargs: Any,
) -> str: ...

async def offload_tool_result(
    self,
    session_id: str,
    tool_result: ToolResultBlock,
    **kwargs: Any,
) -> str: ...
```

**Parameters:**

| Parameter | Type | Meaning |
|-----------|------|---------|
| `session_id` | `str` | Identifies the agent session; used to namespace stored content. |
| `msgs` | `list[Msg]` | Compressed messages to persist. |
| `tool_result` | `ToolResultBlock` | Truncated tool result to persist. |
| `**kwargs` | `Any` | Implementation-specific extra arguments. |

**Returns:** `str` — a reference to the persisted content (file path for `LocalWorkspace`, URI such as `s3://...` for custom backends).

---

### LocalWorkspace

A built-in `Offloader` implementation that organizes offloaded content on the local filesystem under a `workdir`. Also serves as the agent's working environment.

**Import:**

```python
from agentscope.workspace import LocalWorkspace
```

**Constructor parameter:**

| Parameter | Type | Meaning |
|-----------|------|---------|
| `workdir` | `str` | Root directory under which offloaded content is organized. |

**Must be initialized** with `await workspace.initialize()` before use.

**Usage as an agent offloader:**

```python
from agentscope.agent import Agent
from agentscope.workspace import LocalWorkspace

workspace = LocalWorkspace(workdir="/tmp/agent_workspace")
await workspace.initialize()

agent = Agent(
    name="my_agent",
    system_prompt="...",
    model=model,
    toolkit=toolkit,
    offloader=workspace,
)
```

**On-disk layout under `{workdir}`:**

```
{workdir}/
├── data/
│   └── {sha256}.png
├── sessions/
│   └── {session_id}/
│       ├── context.jsonl
│       └── tool_result-{tool_id}.txt
└── skills/
```

- **`sessions/{session_id}/`** — one directory per agent session. Compressed messages append to `context.jsonl`; each truncated tool result becomes an individual `tool_result-{tool_id}.txt` file.
- **`data/`** — multimodal files, deduplicated by SHA-256 hash (e.g. `{sha256}.png`).
- **`skills/`** — workspace skill directory.

---

### Custom Offloader (S3Offloader example)

To target non-filesystem backends (databases, cloud storage), implement the `Offloader` protocol directly. Example targeting S3:

```python
from typing import Any
from agentscope.message import Msg, ToolResultBlock

class S3Offloader:
    def __init__(self, bucket: str, prefix: str) -> None:
        self.bucket = bucket
        self.prefix = prefix

    async def offload_context(
        self,
        session_id: str,
        msgs: list[Msg],
        **kwargs: Any,
    ) -> str:
        key = f"{self.prefix}/sessions/{session_id}/context.jsonl"
        content = "\n".join(m.model_dump_json() for m in msgs)
        await self._upload(self.bucket, key, content)
        return f"s3://{self.bucket}/{key}"

    async def offload_tool_result(
        self,
        session_id: str,
        tool_result: ToolResultBlock,
        **kwargs: Any,
    ) -> str:
        key = f"{self.prefix}/sessions/{session_id}/tool_result-{tool_result.id}.txt"
        # Extract text content from the tool result blocks and upload.
        ...
        return f"s3://{self.bucket}/{key}"
```

Key points the guardian should enforce for a custom offloader:
- Both methods must be `async` and return a `str` reference.
- `offload_context` serializes each `Msg` (the example uses `m.model_dump_json()`) joined by newlines (JSONL).
- `offload_tool_result` keys by `tool_result.id`.

---

## Configuration

All configuration is supplied through `ContextConfig` (passed to `Agent(..., context_config=...)` or to `compress_context(context_config=...)`).

| Option | Type | Controls |
|--------|------|----------|
| `trigger_ratio` | `float` (max `0.9`) | Token-usage threshold (as a ratio of model context size) at which compression activates. |
| `reserve_ratio` | `float` | Proportion of context tokens kept as recent (uncompressed) messages after compression. |
| `tool_result_limit` | `int` | Max tokens per tool result before truncation. |
| `compression_prompt` | `str` | Prompt guiding the model's summary generation. |
| `summary_template` | `str` | Template formatting the summary into the context. |
| `summary_schema` | `dict` | JSON Schema constraining the structured summary output. |

The offloader is configured separately via the `Agent(..., offloader=...)` parameter (any object implementing the `Offloader` protocol, e.g. `LocalWorkspace`).

---

## Usage Patterns

### Automatic compression (the default path)

Compression executes **automatically before each reasoning step**. The documented pipeline:

1. **Count tokens** — totals system prompt, summary, context, and tool schemas.
2. **Check threshold** — if tokens exceed `trigger_ratio × context_size`, activate compression.
3. **Split messages** — mark older messages for compression; preserve recent messages within `reserve_ratio × context_size`.
4. **Generate summary** — model produces a structured summary with **five fields**:
   - `task_overview`
   - `current_state`
   - `important_discoveries`
   - `next_steps`
   - `context_to_preserve`
5. **Update state** — the summary replaces the compressed messages; reserved messages become the new context.

### Manual compression

```python
# Using agent's default config
await agent.compress_context()

# Override config for single call
await agent.compress_context(
    context_config=ContextConfig(trigger_ratio=0.5, reserve_ratio=0.1),
)
```

### Tool-result truncation markers

When a tool output exceeds `tool_result_limit`, it is split: the reserved portion stays in context, the offloaded portion goes to external storage. A truncation marker is inserted.

**Without an offloader attached:**

```
<<<TRUNCATED>>>
<system-reminder>The remaining content has been omitted for limited context.</system-reminder>
```

**With an offloader attached** (the reminder includes a file reference):

```
<<<TRUNCATED>>>
<system-reminder>The remaining content has been omitted for limited context. You can refer to the file in '/path/to/tool_result-<id>.txt' for the truncated content if needed.</system-reminder>
```

### Attaching a LocalWorkspace offloader

```python
from agentscope.agent import Agent
from agentscope.workspace import LocalWorkspace

workspace = LocalWorkspace(workdir="/tmp/agent_workspace")
await workspace.initialize()

agent = Agent(
    name="my_agent",
    system_prompt="...",
    model=model,
    toolkit=toolkit,
    offloader=workspace,
)
```

---

## Gotchas & Version Notes

- **`trigger_ratio` is capped at `0.9`.** Do not set it higher — the docs explicitly state max `0.9`.
- **`compress_context` is async.** Always `await` it. Both `Offloader` methods (`offload_context`, `offload_tool_result`) are also `async` and return `str`.
- **`LocalWorkspace` requires initialization.** Call `await workspace.initialize()` before passing it as an offloader; skipping this is a likely bug.
- **The structured summary has exactly five fields:** `task_overview`, `current_state`, `important_discoveries`, `next_steps`, `context_to_preserve`. Custom `summary_schema` / `summary_template` should align with these.
- **Truncation marker behavior depends on whether an offloader is attached.** Without an offloader, truncated tool content is lost (only `<<<TRUNCATED>>>` + a generic reminder remain). With an offloader, the reminder points to a `tool_result-<id>.txt` file. If preserving truncated content matters, attach an offloader.
- **Compression is automatic before every reasoning step** — manual `compress_context()` calls are an override/supplement, not the primary mechanism.
- **Custom offloaders must implement the full async signatures** including `**kwargs: Any`; key context by `session_id` and tool results by `tool_result.id` (per the `Offloader` protocol contract). `offload_context` serializes messages as JSONL (`m.model_dump_json()` per line in the reference example).
- **Token count includes tool schemas**, not just messages — be aware when reasoning about why compression triggered.
- **Imports:** `ContextConfig` and `Agent` come from `agentscope.agent`; `LocalWorkspace` from `agentscope.workspace`; `Msg` and `ToolResultBlock` from `agentscope.message`.
- This page targets **AgentScope v2** docs (`docs.agentscope.io/v2`); the installed package is **agentscope 1.0.20**. No explicit deprecations or "use X instead of Y" guidance appear on this page.

## Related Reading (referenced by the page)
- **Workspace** — built-in offloader implementations and the agent working environment.
- **Agent** — the ReAct loop and how context flows through reasoning steps.
- **Middleware** — intercepting model calls and system-prompt composition.
- **Tool** — tools producing results subject to compression/truncation.
