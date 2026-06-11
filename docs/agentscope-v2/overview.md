# Overview & Quickstart

> Source:
> - https://docs.agentscope.io/v2/index.md
> - https://docs.agentscope.io/v2/quickstart.md
>
> Documentation index for discovering all pages: https://docs.agentscope.io/llms.txt

> VERSION NOTE: These docs describe **AgentScope 2.0**. The installed package in this
> repo is **agentscope 1.0.20**. AgentScope 2.0 is described by the docs as a
> **breaking change from 1.0** with significant changes to core abstractions, APIs and
> architecture. Treat every API on this page as the **2.0 target surface**; it may not
> match the 1.x API actually installed. See "Gotchas & Version Notes" below.

## Overview

AgentScope 2.0 is a major update to the agent framework focused on improving the
developer experience and making it easier to build and run agents in production.

It is explicitly a **breaking change from 1.0**, with significant improvements to the
core abstractions, APIs and architecture. The docs recommend users migrate to 2.0.

Tagline: "More secure, more efficient, more flexible, and more complete agent
development."

### Major changes / improvements in 2.0

- **Event System** — Every step the agent takes (text, thinking, tool call, tool
  result) is observable as a typed stream, enabling rich responsive UIs and
  integration with AG-UI or A2A without writing adapters.
- **Execution Security** — Dangerous tool calls can be denied or held for review;
  untrusted code can run inside a sandbox. The agent never silently touches the host
  or leaks credentials.
- **Human-in-the-loop** — Users can confirm or edit tool arguments mid-run; sensitive
  actions can be handed off to your own backend instead of executed in-process, with
  the agent resuming exactly where it paused.
- **More Efficient** — Multi-tool steps finish faster through concurrent execution;
  long conversations stay within the context window automatically; oversized tool
  outputs no longer blow up the prompt; transient provider failures fall back
  gracefully.
- **Workspace System** — Move an agent from a laptop to a Docker host or an E2B
  sandbox by changing one line, with working directory, MCP clients and skills cleanly
  isolated per user, agent or session.
- **Agent Service** — Host any agent over REST + SSE with multi-tenant, multi-session
  concurrency, resumable streams, durable sessions, scheduled runs and managed
  credentials, without writing the service plumbing yourself.

### Feature navigation (from index page CardGroup)

| Feature | Description | Link |
|---|---|---|
| Event System | Observe every step of the agent and stream it into your UI. | /v2/building-blocks/message-and-event |
| Execution Security | Gate or sandbox dangerous tool calls before they touch the host. | /v2/building-blocks/permission-system |
| Human-in-the-loop | Let users review and edit tool arguments before execution, or delegate sensitive actions to your own backend. | /v2/building-blocks/message-and-event |
| Efficient Agent | Tool calls are auto-batched and run concurrently or sequentially based on each tool's properties. | /v2/building-blocks/agent |
| Workspace System | Swap Local, Docker or E2B without rewriting the agent. | /v2/building-blocks/workspace |
| Agent Service | Ship agents over REST + SSE with multi-tenant, multi-session concurrency, sessions, schedules and credentials. | /v2/deploy/agent-service |

For migration planning, the docs point to the [Changelog](/v2/change-log).

## API Reference

The quickstart page documents the following symbols. Signatures below reflect exactly
the names, import paths and arguments shown in the docs. Where the docs do not list a
full signature, only the documented arguments are recorded (do not assume others).

### `agentscope.__version__`

Module-level attribute used to verify installation.

```python
import agentscope
print(agentscope.__version__)
```

### `Agent` (`agentscope.agent.Agent`)

The minimal agent class. Two documented entry points: `reply` returns the final
message; `reply_stream` yields incremental events as the agent reasons and acts.

Import:
```python
from agentscope.agent import Agent
```

Constructor arguments shown in the docs:

| Param | Type (as documented) | Default | Meaning |
|---|---|---|---|
| `name` | str | (none shown) | Display/identity name of the agent (e.g. `"Friday"`). |
| `system_prompt` | str | (none shown) | The agent's system prompt. |
| `model` | chat model instance | (none shown) | The chat model backing the agent (e.g. a `DashScopeChatModel`). |
| `toolkit` | `Toolkit` | (none shown) | The toolkit of tools the agent may call. |

> Note: The docs only show these four keyword arguments. No defaults are shown for any
> of them in the quickstart.

#### Method: `Agent.reply(user_msg)`

- Async. `reply_msg = await agent.reply(user_msg)`.
- Awaits and returns the **final assistant message**.
- Return value is an `AssistantMsg` whose `content` is a **list of blocks** (inspect
  text blocks, tool calls, etc. as needed).

#### Method: `Agent.reply_stream(user_msg)`

- Async generator. `async for event in agent.reply_stream(user_msg):`.
- Yields **incremental events** (text deltas, tool calls, ...).
- Dispatch on `event.type` (an `EventType`); each branch handles one event kind.

### `EventType` (`agentscope.event.EventType`)

Enum of event kinds yielded by `reply_stream`. Documented members:

| Member | Meaning (from docs) |
|---|---|
| `EventType.TEXT_BLOCK_DELTA` | Streaming text chunk from the model — append to UI / stdout. |
| `EventType.TOOL_CALL_START` | The agent is about to invoke a tool — surface the call. |

The docs also reference, in a comment, additional event kinds not enumerated by name:
"thinking blocks, tool results, reply end, ...".

Import:
```python
from agentscope.event import EventType
```

### `UserMsg` (`agentscope.message.UserMsg`)

Represents a user message passed to `reply` / `reply_stream`.

Import:
```python
from agentscope.message import UserMsg
```

Constructor arguments shown in the docs:

| Param | Type | Default | Meaning |
|---|---|---|---|
| `name` | str | (none shown) | Author name, e.g. `"user"`. |
| `content` | str | (none shown) | The message text, e.g. `"Hello, who are you?"`. |

Usage: `user_msg = UserMsg(name="user", content="Hello, who are you?")`

### `AssistantMsg` (`agentscope.message`)

Return type of `Agent.reply`. Its `content` attribute is a **list of blocks** (text
blocks, tool calls, etc.). The quickstart references it but does not import it
explicitly; it is the documented return type of `reply`.

### `DashScopeCredential` (`agentscope.credential.DashScopeCredential`)

Credential object for DashScope.

Import:
```python
from agentscope.credential import DashScopeCredential
```

Constructor arguments shown in the docs:

| Param | Type | Default | Meaning |
|---|---|---|---|
| `api_key` | str | (none shown) | DashScope API key. In the example: `os.getenv("DASHSCOPE_API_KEY")`. |

### `DashScopeChatModel` (`agentscope.model.DashScopeChatModel`)

Chat model backed by DashScope.

Import:
```python
from agentscope.model import DashScopeChatModel
```

Constructor arguments shown in the docs:

| Param | Type | Default | Meaning |
|---|---|---|---|
| `credential` | `DashScopeCredential` | (none shown) | A DashScope credential instance. |
| `model` | str | (none shown) | Model id, e.g. `"qwen-plus"`. |

### `Toolkit` (`agentscope.tool.Toolkit`)

Container of tools given to an agent.

Import:
```python
from agentscope.tool import Toolkit, Bash, Read, Write, Edit
```

Constructor arguments shown in the docs:

| Param | Type | Default | Meaning |
|---|---|---|---|
| `tools` | list of tool instances | (none shown) | Tools the agent may call, e.g. `[Bash(), Read(), Write(), Edit()]`. An empty toolkit is also valid per the prose ("an empty toolkit"). |

### Built-in tools: `Bash`, `Read`, `Write`, `Edit` (`agentscope.tool`)

Built-in tool classes, instantiated with no arguments in the docs and passed to
`Toolkit(tools=[...])`.

| Tool | Documented usage |
|---|---|
| `Bash` | `Bash()` |
| `Read` | `Read()` |
| `Write` | `Write()` |
| `Edit` | `Edit()` |

No constructor parameters are shown for any of these in the quickstart.

### Alternate provider pair: `OpenAICredential` / `OpenAIChatModel`

Mentioned as the swap-in pair for OpenAI: "swap `DashScopeCredential` and
`DashScopeChatModel` for the matching pair (e.g. `OpenAICredential` and
`OpenAIChatModel`)." No signatures shown in the quickstart.

## Configuration

| Option | Where | Controls |
|---|---|---|
| `DASHSCOPE_API_KEY` (env var) | Read via `os.getenv("DASHSCOPE_API_KEY")` into `DashScopeCredential(api_key=...)` | DashScope authentication. Must be set in the environment before running the script. |
| `api_key` | `DashScopeCredential(api_key=...)` | The credential's API key. |
| `model` | `DashScopeChatModel(model="qwen-plus")` | Which model to call (example uses `"qwen-plus"`). |
| `credential` | `DashScopeChatModel(credential=...)` | The credential the model uses. |
| `name` | `Agent(name=...)` / `UserMsg(name=...)` | Identity/author name. |
| `system_prompt` | `Agent(system_prompt=...)` | Agent system prompt. |
| `tools` | `Toolkit(tools=[...])` | Tools available to the agent. |
| `content` | `UserMsg(content=...)` | User message text. |
| `event.type` | dispatch in `reply_stream` loop | Selects handling per event kind via `EventType`. |

### Installation configuration

| Requirement / option | Value |
|---|---|
| Python version | 3.11+ |
| Recommended package manager | `uv` |
| PyPI install | `uv pip install agentscope` |
| Source install | clone `-b main https://github.com/agentscope-ai/agentscope`, then `uv pip install -e .` |
| Extra: `full` | extra deps for model APIs, tool functions and more |
| Extra: `dev` | development deps (testing and documentation tools) |

Note: the source-clone command in the quickstart uses the org `agentscope-ai`
(`git clone -b main https://github.com/agentscope-ai/agentscope`).

## Usage Patterns

### Verify installation

```python
import agentscope

print(agentscope.__version__)
```

### Minimal agent — full quickstart example (verbatim)

```python
import asyncio
import os

from agentscope.agent import Agent
from agentscope.credential import DashScopeCredential
from agentscope.event import EventType
from agentscope.message import UserMsg
from agentscope.model import DashScopeChatModel
from agentscope.tool import Toolkit, Bash, Read, Write, Edit


async def main() -> None:
    agent = Agent(
        name="Friday",
        system_prompt="You are a helpful assistant named Friday.",
        model=DashScopeChatModel(
            credential=DashScopeCredential(
                api_key=os.getenv("DASHSCOPE_API_KEY"),
            ),
            model="qwen-plus",
        ),
        toolkit=Toolkit(tools=[Bash(), Read(), Write(), Edit()]),
    )

    user_msg = UserMsg(name="user", content="Hello, who are you?")

    # Option 1: await the final assistant message.
    reply_msg = await agent.reply(user_msg)
    # `reply_msg` is an `AssistantMsg` whose `content` is a list of blocks.
    # Inspect text blocks, tool calls, etc. as needed.
    ...

    # Option 2: stream incremental events (text deltas, tool calls, ...).
    async for event in agent.reply_stream(user_msg):
        # Dispatch on `event.type` — each branch handles one event kind.
        match event.type:
            case EventType.TEXT_BLOCK_DELTA:
                # Streaming text chunk from the model — append to UI / stdout.
                ...
            case EventType.TOOL_CALL_START:
                # The agent is about to invoke a tool — surface the call.
                ...
            case _:
                # Other events: thinking blocks, tool results, reply end, ...
                ...


asyncio.run(main())
```

### Install commands (verbatim)

From PyPI:
```bash
uv pip install agentscope
```

From source:
```bash
git clone -b main https://github.com/agentscope-ai/agentscope
cd agentscope
uv pip install -e .
```

Extra dependencies (`full`):

- Windows users:
```bash
uv pip install agentscope[full]
```
- Mac and Linux users:
```bash
uv pip install agentscope\[full\]
```

## Gotchas & Version Notes

- **Installed version mismatch (CRITICAL).** These docs are for AgentScope **2.0**.
  The package installed in this repo is **1.0.20**. The docs state 2.0 is a
  **breaking change** from 1.0 with significant changes to core abstractions, APIs and
  architecture. APIs documented here (e.g. `agentscope.agent.Agent`,
  `agentscope.event.EventType`, `agentscope.credential`, `agentscope.message.UserMsg`,
  `agentscope.tool.Toolkit`) may not exist or may differ in 1.0.20. Verify against the
  installed package before relying on any symbol.

- **Class name is `Agent`, not `ReActAgent`.** The 2.0 quickstart uses
  `from agentscope.agent import Agent`. Do not assume the 1.x `ReActAgent` shape.

- **Python 3.11+ required.** The quickstart relies on structural pattern matching
  (`match`/`case`), which itself needs Python 3.10+, and AgentScope requires 3.11+.

- **Shell bracket escaping for extras.** The `full` extra must be written differently
  per OS: `agentscope[full]` on Windows, but `agentscope\[full\]` on Mac/Linux (the
  shell would otherwise glob the brackets). Using the wrong form on Mac/Linux can fail.

- **`DASHSCOPE_API_KEY` must be set** in the environment before running; the example
  reads it via `os.getenv("DASHSCOPE_API_KEY")`. A missing key yields `None`.

- **`reply` vs `reply_stream`.** `reply` returns the final `AssistantMsg` (whose
  `content` is a list of blocks). `reply_stream` is an async generator of events to
  dispatch on `event.type`. Both are awaited/iterated inside an async context
  (`asyncio.run(main())`).

- **`AssistantMsg.content` is a list of blocks**, not a plain string. Do not treat the
  reply content as a string; iterate/inspect blocks (text blocks, tool calls, etc.).

- **Provider swap pattern.** To change providers, swap the credential+model pair
  together (e.g. `DashScopeCredential`+`DashScopeChatModel` →
  `OpenAICredential`+`OpenAIChatModel`). Don't mix a credential from one provider with
  a model from another.

- **`uv` recommended.** Docs recommend installing via `uv`; commands are shown as
  `uv pip install ...`.

- **Source org is `agentscope-ai`.** The clone URL is
  `https://github.com/agentscope-ai/agentscope` on branch `main`.

- **Undocumented details are not invented here.** No defaults are shown for any
  constructor argument in the quickstart; do not assume them. Additional `EventType`
  members beyond `TEXT_BLOCK_DELTA` and `TOOL_CALL_START` exist (the docs reference
  "thinking blocks, tool results, reply end, ...") but are not named on these pages.
