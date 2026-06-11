# Agent

> Source: https://docs.agentscope.io/v2/building-blocks/agent.md
>
> Documents AgentScope v2 (installed package `agentscope` 1.0.20). This file is the single source of truth a code-review guardian consults before approving changes to code that uses the AgentScope `Agent` unit.

## Overview

The AgentScope `Agent` is a **stateless reasoning-acting loop engine** that integrates models, tools, the permission system, human-in-the-loop, context management, middlewares, state management, and the event system into a single unified interface.

"Stateless" means the agent does not hold the conversation as hidden internal state across processes; the full conversation/context lives in an `AgentState` object that can be injected at construction and read back out (`agent.state`) for persistence. This is what enables save/restore and horizontal scaling.

The reasoning-acting loop executed on each `reply` call:
1. Handle the input message(s).
2. Optionally compress context (if token usage crosses the configured trigger ratio).
3. Call the LLM for reasoning.
4. If the model returns tool calls, batch and execute them, running permission checks first.
   - Denied calls produce error tool results.
   - Confirmed calls proceed.
   - Calls requiring human or external action **pause** the loop and surface an event; the caller resumes by feeding a result event back into `reply` / `reply_stream`.

The four primary interfaces:
- `reply(inputs)` — run the loop, return the final message.
- `reply_stream(inputs)` — yield `AgentEvent` objects in real time.
- `observe(msgs)` — add messages to context **without** triggering reasoning.
- `compress_context(context_config)` — manually compress context.

## API Reference

### Agent

Core reasoning-acting loop engine.

```python
from agentscope.agent import Agent
from agentscope.model import DashScopeChatModel
from agentscope.credential import DashScopeCredential

agent = Agent(
    name="my_agent",
    system_prompt="You are a helpful assistant.",
    model=DashScopeChatModel(
        credential=DashScopeCredential(api_key="YOUR_API_KEY"),
        model="qwen-max",
    ),
)
```

**Constructor parameters**

| Parameter | Type | Default | Meaning |
|-----------|------|---------|---------|
| `name` | `str` | required | Agent name. |
| `system_prompt` | `str` | required | System prompt for the agent. |
| `model` | `ChatModelBase` | required | The chat model (e.g. `DashScopeChatModel`). |
| `toolkit` | `Toolkit \| None` | `None` | Tools, MCP clients, and skills. |
| `state` | `AgentState \| None` | auto-created | Restored conversation/context state; a fresh `AgentState()` is created if omitted. |
| `offloader` | `Offloader \| None` | `None` | Offloads compressed context and large tool results to persistent storage. |
| `middlewares` | `list[MiddlewareBase] \| None` | `None` | Lifecycle hooks. |
| `model_config` | `ModelConfig` | default | Retry counts and fallback models. |
| `context_config` | `ContextConfig` | default | Context compression behavior. |
| `react_config` | `ReActConfig` | default | Max iterations and rejection handling. |

#### Agent.reply

```
reply(inputs: Msg | list[Msg] | UserConfirmResultEvent | ExternalExecutionResultEvent | None) -> Msg
```

Runs the reasoning-acting loop, consuming events internally, and returns the final `Msg` when the agent finishes or pauses. Accepts a normal message (or list), or a resume event (`UserConfirmResultEvent` / `ExternalExecutionResultEvent`) to continue after a human-in-the-loop pause.

```python
import asyncio
from agentscope.message import UserMsg

async def main():
    msg = UserMsg(name="user", content="What files are in the current directory?")
    result = await agent.reply(msg)
    print(result.get_text_content())

asyncio.run(main())
```

#### Agent.reply_stream

```
reply_stream(inputs: Msg | list[Msg] | UserConfirmResultEvent | ExternalExecutionResultEvent | None) -> AsyncIterator[AgentEvent]
```

Yields `AgentEvent` objects as they are produced, enabling real-time streaming. Text tokens are streamed via events that carry a `delta` attribute (incremental content).

```python
async def main():
    msg = UserMsg(name="user", content="Summarize the README.")
    async for event in agent.reply_stream(msg):
        if hasattr(event, "delta"):
            print(event.delta, end="", flush=True)

asyncio.run(main())
```

#### Agent.observe

```
observe(msgs: list[Msg]) -> None
```

Injects messages into context **without** triggering a reply/reasoning turn. Used to feed another agent's message into this agent's context.

```python
await agent.observe(other_agent_msg)
```

#### Agent.compress_context

```
compress_context(context_config: ContextConfig | None = None) -> None
```

Manually compresses context when the token count exceeds the threshold. With no argument it uses the agent's configured `context_config`; pass a `ContextConfig` to override for this call only.

```python
from agentscope.agent import ContextConfig

# Use the agent's default config
await agent.compress_context()

# Or pass a custom config for this call only
await agent.compress_context(
    ContextConfig(trigger_ratio=0.6, reserve_ratio=0.2)
)
```

### ContextConfig

Configuration for context compression behavior. Imported from `agentscope.agent`.

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `trigger_ratio` | `float` | `0.7` | Compress when this ratio of the model's context length is used (70% by default). |
| `reserve_ratio` | `float` | `0.2` | Keep the most recent messages at this ratio after compression (most recent 20%). |
| `tool_result_limit` | `int` | `1000` | Truncate tool results at this many tokens. |

### AgentState

Pydantic model holding the full conversation context, compression summary, permission rules, tool state, and reply position for resuming agents. Serializable to JSON. A fresh instance is `AgentState()`. Read the live state via `agent.state`.

```python
from agentscope.state import AgentState
state = AgentState()
```

### RedisStorage

Built-in storage backend. Organizes state under a `(user_id, agent_id, session_id)` hierarchy. Used as an async context manager.

```python
from agentscope.app.storage import RedisStorage

async with RedisStorage(host="localhost", port=6379) as storage:
    ...
```

**Constructor parameters:** `host` (`str`), `port` (`int`).

#### RedisStorage.get_session

```
get_session(user_id: str, agent_id: str, session_id: str) -> SessionRecord | None
```

Loads a `SessionRecord` containing the saved `AgentState`. Returns `None` if not found. Access the state via `record.state`.

#### RedisStorage.update_session_state

```
update_session_state(user_id: str, agent_id: str, session_id: str, state: AgentState) -> None
```

Persists an updated `AgentState`. **Requires a pre-existing session** — raises `KeyError` if the session does not exist. Call `upsert_session` first on the very first turn.

#### RedisStorage.upsert_session

```
upsert_session(user_id: str, agent_id: str, session_id: str) -> ...
```

Creates the session record on the first turn before `update_session_state` can be used.

### SessionRecord

Storage record containing a saved `AgentState`, accessible via the `.state` field.

### Event Types

#### RequireUserConfirmEvent
Emitted when a tool call requires user approval (the permission system returns `ASK`).
Fields: `reply_id` (`str`), `tool_calls` (`list[ToolCallBlock]`).

#### ConfirmResult
User confirmation response for a single tool call.
Fields: `confirmed` (`bool`), `tool_call` (`ToolCallBlock`, passed back, optionally modified), `rules` (`list[PermissionRule]`, accept to auto-allow in future).

#### UserConfirmResultEvent
Resumes the agent after user confirmation.
Fields: `reply_id` (`str`), `confirm_results` (`list[ConfirmResult]`).

#### RequireExternalExecutionEvent
Emitted when a tool marked for external execution is called.
Fields: `reply_id` (`str`), `tool_calls` (`list[ToolCallBlock]`).

#### ExternalExecutionResultEvent
Resumes the agent with external execution results.
Fields: `reply_id` (`str`), `execution_results` (`list[ToolResultBlock]`).

#### ToolCallBlock
Fields: `id` (`str`), `name` (`str`), `input` (`str`, JSON-encoded), `suggested_rules` (`list[PermissionRule]`).

#### AgentEvent
Generic base event yielded during streaming. Streaming text events carry a `delta` attribute for incremental content.

### Message / Result Blocks

#### UserMsg
User message object. Constructed with `name` and `content`. `result.get_text_content()` returns the text of a returned message.

#### ToolResultBlock
Wraps tool execution results.
Fields: `id` (`str`), `name` (`str`), `output` (`list`, e.g. of `TextBlock`), `state` (`ToolResultState`).

#### TextBlock
Text content wrapper. Field: `text` (`str`).

#### ToolResultState
Enum of tool result states. Known value: `ToolResultState.SUCCESS`.

## Configuration

| Config object | Field | Type | Default | Controls |
|---------------|-------|------|---------|----------|
| `ContextConfig` | `trigger_ratio` | float | `0.7` | Compression triggers at this fraction of model context length. |
| `ContextConfig` | `reserve_ratio` | float | `0.2` | Fraction of most-recent messages retained after compression. |
| `ContextConfig` | `tool_result_limit` | int | `1000` | Token cap for tool results before truncation. |
| `ModelConfig` | (retry/fallback) | — | default | Retry counts and fallback models. |
| `ReActConfig` | (iterations/rejection) | — | default | Max ReAct iterations and rejection handling. |

## Usage Patterns

### Agent with tools, MCP, and skills

```python
import os
from agentscope.agent import Agent
from agentscope.tool import Toolkit, Bash, Edit, Grep, Read, Write
from agentscope.mcp import MCPClient, HttpMCPConfig
from agentscope.model import DashScopeChatModel
from agentscope.credential import DashScopeCredential

agent = Agent(
    name="my_agent",
    system_prompt="You are a helpful assistant.",
    model=DashScopeChatModel(
        credential=DashScopeCredential(api_key="YOUR_API_KEY"),
        model="qwen-max",
    ),
    toolkit=Toolkit(
        tools=[Bash(), Edit(), Grep(), Read(), Write()],
        mcps=[
            MCPClient(
                name="amap",
                is_stateful=False,
                mcp_config=HttpMCPConfig(
                    url=f"https://mcp.amap.com/mcp?key={os.environ['AMAP_API_KEY']}",
                ),
            ),
        ],
        skills_or_loaders=["./skills"],
    ),
)
```

### Custom context compression config

```python
from agentscope.agent import Agent, ContextConfig
from agentscope.model import DashScopeChatModel
from agentscope.credential import DashScopeCredential

agent = Agent(
    name="my_agent",
    system_prompt="You are a helpful assistant.",
    model=DashScopeChatModel(
        credential=DashScopeCredential(api_key="YOUR_API_KEY"),
        model="qwen-max",
    ),
    context_config=ContextConfig(
        trigger_ratio=0.7,       # compress when 70% of context is used
        reserve_ratio=0.2,       # keep the most recent 20% after compression
        tool_result_limit=1000,  # truncate tool results at 1000 tokens
    ),
)
```

### Human-in-the-loop: user confirmation

```python
from agentscope.event import RequireUserConfirmEvent

# 1. Receive the confirmation request
async for event in agent.reply_stream(msg):
    if isinstance(event, RequireUserConfirmEvent):
        for tc in event.tool_calls:
            print(f"Tool: {tc.name}, Input: {tc.input}")
            print(f"Suggested rules: {tc.suggested_rules}")

# 2. Build the results
from agentscope.event import ConfirmResult, UserConfirmResultEvent

confirm_results = []
for tc in event.tool_calls:
    confirm_results.append(ConfirmResult(
        confirmed=True,           # or False to deny
        tool_call=tc,             # pass back (optionally modified)
        rules=tc.suggested_rules, # accept rules for future auto-allow
    ))

# 3. Resume the agent
confirm_event = UserConfirmResultEvent(
    reply_id=event.reply_id,
    confirm_results=confirm_results,
)
result = await agent.reply(confirm_event)
```

### Human-in-the-loop: external tool execution

```python
from agentscope.event import RequireExternalExecutionEvent

# 1. Receive the request
async for event in agent.reply_stream(msg):
    if isinstance(event, RequireExternalExecutionEvent):
        for tc in event.tool_calls:
            print(f"Execute externally: {tc.name}({tc.input})")

# 2. Build the results
from agentscope.message import ToolResultBlock, TextBlock, ToolResultState
from agentscope.event import ExternalExecutionResultEvent

execution_results = []
for tc in event.tool_calls:
    output = await run_external_operation(tc.name, tc.input)
    execution_results.append(ToolResultBlock(
        id=tc.id,
        name=tc.name,
        output=[TextBlock(text=output)],
        state=ToolResultState.SUCCESS,
    ))

# 3. Resume the agent
external_event = ExternalExecutionResultEvent(
    reply_id=event.reply_id,
    execution_results=execution_results,
)
result = await agent.reply(external_event)
```

### Persist and restore agent state with Redis

```python
import asyncio
from agentscope.agent import Agent
from agentscope.state import AgentState
from agentscope.model import DashScopeChatModel
from agentscope.credential import DashScopeCredential
from agentscope.message import UserMsg
from agentscope.app.storage import RedisStorage

USER_ID = "user_123"
AGENT_ID = "agent_456"
SESSION_ID = "session_789"

async def main():
    async with RedisStorage(host="localhost", port=6379) as storage:
        # Load state, fall back to a fresh state if not found
        record = await storage.get_session(
            user_id=USER_ID,
            agent_id=AGENT_ID,
            session_id=SESSION_ID,
        )
        state = record.state if record else AgentState()

        # Create the agent with the restored state
        agent = Agent(
            name="my_agent",
            system_prompt="You are a helpful assistant.",
            model=DashScopeChatModel(
                credential=DashScopeCredential(api_key="YOUR_API_KEY"),
                model="qwen-max",
            ),
            state=state,
        )

        # Run a reply turn
        result = await agent.reply(
            UserMsg(name="user", content="Continue where we left off."),
        )
        print(result.get_text_content())

        # Persist the updated state back to Redis
        await storage.update_session_state(
            user_id=USER_ID,
            agent_id=AGENT_ID,
            session_id=SESSION_ID,
            state=agent.state,
        )

asyncio.run(main())
```

## Gotchas & Version Notes

- **This is AgentScope v2 (`agentscope` 1.0.x).** Construct agents with `Agent(name=..., system_prompt=..., model=...)`. Use the unified `reply` / `reply_stream` / `observe` / `compress_context` interface — do not assume an older `agentscope.agents.*` ReActAgent-style API.
- **`update_session_state` requires a pre-existing session.** It raises `KeyError` if the session does not exist. On the first turn call `upsert_session(user_id, agent_id, session_id)` before `update_session_state`. Pattern for loading: `state = record.state if record else AgentState()`.
- **`compress_context` can raise `RuntimeError`.** If the system prompt alone exceeds the compression threshold, compression cannot proceed — keep the system prompt concise or increase the model's context length.
- **`observe` does NOT trigger reasoning.** Use it only to inject messages into context. Use `reply` / `reply_stream` to actually run the loop.
- **Resume after a pause by feeding a result event into `reply`/`reply_stream`,** not a plain message. After a `RequireUserConfirmEvent`, resume with a `UserConfirmResultEvent`; after a `RequireExternalExecutionEvent`, resume with an `ExternalExecutionResultEvent`. Carry over the original `event.reply_id` into the resume event.
- **Permission rules:** `ToolCallBlock.suggested_rules` are `PermissionRule` objects. Pass them back via `ConfirmResult(rules=...)` to auto-allow matching calls in future turns. Set `confirmed=False` to deny a tool call (denied calls produce error tool results, they do not crash the loop).
- **Tool results exceeding `tool_result_limit` are automatically truncated.** When an `Offloader` is configured, the truncated overflow is offloaded to persistent storage and the agent receives a readable disk reference it can read on demand.
- **Streaming:** not every `AgentEvent` from `reply_stream` is a text token — guard text handling with `if hasattr(event, "delta")` (or `isinstance` checks for the human-in-the-loop event types) before consuming `event.delta`.
- **State is the unit of persistence, not the agent.** Because the agent is stateless, persist `agent.state` (an `AgentState`, JSON-serializable Pydantic model) and reconstruct the agent with `state=...` to resume.
- **MCP clients:** configured via `Toolkit(mcps=[MCPClient(name=..., is_stateful=..., mcp_config=HttpMCPConfig(url=...))])`. Skills are loaded via `Toolkit(skills_or_loaders=[...])`.
