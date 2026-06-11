# Message & Event

> Source:
> - https://docs.agentscope.io/v2/building-blocks/message-and-event.md

## Overview

`Message` and `Event` are the two fundamental data structures for agent communication and streaming in AgentScope v2 (installed package `agentscope` 1.0.20).

- **Message** (`Msg`) — the unit of inter-agent communication and persistence. Each `Msg` represents a complete conversation turn that is stored in context and exchanged between agents.
- **Event** (`AgentEvent`) — the unit of frontend interaction and streaming. Events carry incremental progress updates (text tokens, tool call fragments, permission requests) and drive real-time UIs and human-in-the-loop workflows.

Key invariant: a sequence of events produced during a single `reply` call accumulates into **exactly one** assistant `Msg`. The complete message state is always recoverable from its event stream alone (via `append_event` / `appendEvent`).

One assistant message corresponds to one complete `reply` cycle of the agent (repeated reasoning and acting until a final response is produced).

Python import paths used throughout the docs:
- `from agentscope.message import ...` — `Msg`, `UserMsg`, `AssistantMsg`, `SystemMsg`, `TextBlock`, `DataBlock`, `Base64Source`, etc.
- `from agentscope.event import ...` — event classes.

---

## API Reference

### Msg (class)

Represents a single turn in a conversation — a user input, an assistant response, or a system instruction — carrying structured content as a list of typed blocks.

**Core fields**

| Field         | Type                                | Description                                       |
| ------------- | ----------------------------------- | ------------------------------------------------- |
| `id`          | `str`                               | Unique message identifier                         |
| `name`        | `str`                               | Name of the sender                                |
| `role`        | `"user" \| "assistant" \| "system"` | The sender's role                                 |
| `content`     | `list[ContentBlock]`                | Ordered list of content blocks                    |
| `metadata`    | `dict`                              | Arbitrary key-value metadata                      |
| `created_at`  | `str`                               | ISO 8601 timestamp of creation                    |
| `finished_at` | `str \| None`                       | ISO 8601 timestamp when the message was finalized |
| `usage`       | `Usage`                             | Token usage statistics (for assistant messages)   |

**Role constraints (enforced at construction):**
- `user` messages can only contain `TextBlock` and `DataBlock`.
- `system` messages can only contain `TextBlock`.
- `assistant` messages can contain all block types.

**Methods**

| Method                             | Returns                                            | Meaning |
| ---------------------------------- | -------------------------------------------------- | ------- |
| `get_text_content(separator="\n")` | `str \| None` | Concatenated text from all `TextBlock`s, joined by `separator`; `None` if no text. |
| `get_content_blocks(block_type)`   | `list` | Filtered list of blocks by type (e.g. `"tool_call"`). |
| `has_content_blocks(block_type)`   | `bool` | `True` if blocks of the given type exist. |
| `append_event(event)`              | mutates `self` | Applies an `AgentEvent` to incrementally reconstruct the message (see "Reconstruct Messages from Events"). |

`block_type` string values seen in docs: `"tool_call"`, `"tool_result"` (and by extension the type string of each block such as `"text"`, `"data"`, `"thinking"`).

### UserMsg(name, content) — factory

Creates a `Msg` with `role="user"`.

| Param     | Type                                    | Default | Meaning |
| --------- | --------------------------------------- | ------- | ------- |
| `name`    | `str`                                   | —       | Sender name. |
| `content` | `str` or `list[TextBlock \| DataBlock]` | —       | Plain string is auto-wrapped into a `TextBlock`. Only `TextBlock`/`DataBlock` allowed. |

Optional `id` keyword is also accepted (used in the TypeScript/Python reconstruction examples, e.g. `AssistantMsg(name=..., content=[], id=event.reply_id)`).

### AssistantMsg(name, content) — factory

Creates a `Msg` with `role="assistant"`. Allowed content: `str` or `list[ContentBlock]` (all block types).

| Param     | Type                       | Default | Meaning |
| --------- | -------------------------- | ------- | ------- |
| `name`    | `str`                      | —       | Sender name. |
| `content` | `str` or `list[ContentBlock]` | —    | Plain string auto-wrapped into a `TextBlock`. |
| `id`      | `str`                      | (optional) | Used to bind the message to a `reply_id` when reconstructing from events. |

### SystemMsg(name, content) — factory

Creates a `Msg` with `role="system"`. Allowed content: `str` or `list[TextBlock]` (text only).

| Param     | Type                  | Default | Meaning |
| --------- | --------------------- | ------- | ------- |
| `name`    | `str`                 | —       | Sender name. |
| `content` | `str` or `list[TextBlock]` | —  | Plain string auto-wrapped into a `TextBlock`. |

### Content Blocks

| Block             | Description                                                                 | Allowed In              |
| ----------------- | --------------------------------------------------------------------------- | ----------------------- |
| `TextBlock`       | Plain text content                                                          | user, assistant, system |
| `DataBlock`       | Binary data (images, audio) via base64 or URL                               | user, assistant         |
| `ThinkingBlock`   | Model reasoning (chain-of-thought)                                          | assistant               |
| `ToolCallBlock`   | A tool invocation with name, input, and state                              | assistant               |
| `ToolResultBlock` | The output of a tool execution                                             | assistant               |
| `HintBlock`       | Out-of-band hint injected into the conversation (scheduled-task trigger, team message, background-tool result). `hint` field is `str` for plain text or `list[TextBlock \| DataBlock]` for multimodal payloads; `source` carries a small JSON tag the frontend uses to label the hint's origin. | assistant |

Supporting types referenced in examples:
- `TextBlock(text=...)`
- `DataBlock(source=Base64Source(data="...", media_type="image/png"))`
- `Base64Source(data, media_type)` — base64 payload + MIME type.

### ToolCallBlock state values

`ToolCallBlock` carries a state. States referenced in docs: `ASKING` (set when `RequireUserConfirmEvent` is applied via `append_event`). Tool result final states are given by `ToolResultState` (below).

### ToolResultState (enum)

Final state of a tool execution, carried by `ToolResultEndEvent.state` and set into the `ToolResultBlock`:

`SUCCESS`, `ERROR`, `INTERRUPTED`, `DENIED`, `RUNNING`.

### EventBase (base class)

All events inherit from `EventBase`, providing common fields:

| Field        | Type  | Description             |
| ------------ | ----- | ----------------------- |
| `id`         | `str` | Unique event identifier |
| `created_at` | `str` | ISO 8601 timestamp      |

Every event (except where noted) also carries a `reply_id` linking it to the message being constructed. All events within a single reply share the same `reply_id`. Within a reply, `block_id` correlates text/thinking/data block events, and `tool_call_id` correlates tool call and tool result events.

`AgentEvent` is the umbrella type yielded by the agent's streaming reply.

---

### Lifecycle Events

#### ReplyStartEvent — agent begins a new reply

| Field        | Type  | Description                        |
| ------------ | ----- | ---------------------------------- |
| `reply_id`   | `str` | ID of the reply message            |
| `session_id` | `str` | ID of the session                  |
| `name`       | `str` | Agent name                         |
| `role`       | `str` | Agent role (default `"assistant"`) |

#### ReplyEndEvent — agent finishes the reply

| Field        | Type  | Description             |
| ------------ | ----- | ----------------------- |
| `reply_id`   | `str` | ID of the reply message |
| `session_id` | `str` | ID of the session       |

#### ExceedMaxItersEvent — agent reached the maximum reasoning-acting iterations

| Field      | Type  | Description             |
| ---------- | ----- | ----------------------- |
| `reply_id` | `str` | ID of the reply message |
| `name`     | `str` | Agent name              |

---

### Text Streaming Events

#### TextBlockStartEvent — a new text block begins

| Field      | Type  | Description                         |
| ---------- | ----- | ----------------------------------- |
| `reply_id` | `str` | ID of the reply message             |
| `block_id` | `str` | Unique identifier of the text block |

#### TextBlockDeltaEvent — incremental text content arrives

| Field      | Type  | Description                         |
| ---------- | ----- | ----------------------------------- |
| `reply_id` | `str` | ID of the reply message             |
| `block_id` | `str` | Unique identifier of the text block |
| `delta`    | `str` | Incremental text content            |

#### TextBlockEndEvent — the text block is complete

| Field      | Type  | Description                         |
| ---------- | ----- | ----------------------------------- |
| `reply_id` | `str` | ID of the reply message             |
| `block_id` | `str` | Unique identifier of the text block |

---

### Thinking Streaming Events

#### ThinkingBlockStartEvent — a new thinking block begins

| Field      | Type  | Description                             |
| ---------- | ----- | --------------------------------------- |
| `reply_id` | `str` | ID of the reply message                 |
| `block_id` | `str` | Unique identifier of the thinking block |

#### ThinkingBlockDeltaEvent — incremental thinking content arrives

| Field      | Type  | Description                             |
| ---------- | ----- | --------------------------------------- |
| `reply_id` | `str` | ID of the reply message                 |
| `block_id` | `str` | Unique identifier of the thinking block |
| `delta`    | `str` | Incremental thinking text               |

#### ThinkingBlockEndEvent — the thinking block is complete

| Field      | Type  | Description                             |
| ---------- | ----- | --------------------------------------- |
| `reply_id` | `str` | ID of the reply message                 |
| `block_id` | `str` | Unique identifier of the thinking block |

---

### Data Streaming Events

#### DataBlockStartEvent — a new data block begins (image, audio, etc.)

| Field        | Type  | Description                         |
| ------------ | ----- | ----------------------------------- |
| `reply_id`   | `str` | ID of the reply message             |
| `block_id`   | `str` | Unique identifier of the data block |
| `media_type` | `str` | MIME type (e.g. `"image/png"`)      |

#### DataBlockDeltaEvent — incremental binary data arrives

| Field        | Type  | Description                         |
| ------------ | ----- | ----------------------------------- |
| `reply_id`   | `str` | ID of the reply message             |
| `block_id`   | `str` | Unique identifier of the data block |
| `data`       | `str` | Incremental base64-encoded data     |
| `media_type` | `str` | MIME type                           |

#### DataBlockEndEvent — the data block is complete

| Field      | Type  | Description                         |
| ---------- | ----- | ----------------------------------- |
| `reply_id` | `str` | ID of the reply message             |
| `block_id` | `str` | Unique identifier of the data block |

---

### Tool Call Streaming Events

#### ToolCallStartEvent — the agent begins a tool call

| Field            | Type  | Description                        |
| ---------------- | ----- | ---------------------------------- |
| `reply_id`       | `str` | ID of the reply message            |
| `tool_call_id`   | `str` | Unique identifier of the tool call |
| `tool_call_name` | `str` | Name of the tool being called      |

#### ToolCallDeltaEvent — incremental tool call input arrives

| Field          | Type  | Description                             |
| -------------- | ----- | --------------------------------------- |
| `reply_id`     | `str` | ID of the reply message                 |
| `tool_call_id` | `str` | Unique identifier of the tool call      |
| `delta`        | `str` | Incremental JSON fragment of tool input |

#### ToolCallEndEvent — the tool call input is complete

| Field          | Type  | Description                        |
| -------------- | ----- | ---------------------------------- |
| `reply_id`     | `str` | ID of the reply message            |
| `tool_call_id` | `str` | Unique identifier of the tool call |

---

### Tool Result Streaming Events

#### ToolResultStartEvent — tool execution begins

| Field            | Type  | Description                       |
| ---------------- | ----- | --------------------------------- |
| `reply_id`       | `str` | ID of the reply message           |
| `tool_call_id`   | `str` | ID of the corresponding tool call |
| `tool_call_name` | `str` | Name of the tool                  |

#### ToolResultTextDeltaEvent — incremental text output from the tool

| Field          | Type  | Description                       |
| -------------- | ----- | --------------------------------- |
| `reply_id`     | `str` | ID of the reply message           |
| `tool_call_id` | `str` | ID of the corresponding tool call |
| `delta`        | `str` | Incremental text content          |

#### ToolResultDataDeltaEvent — binary data output from the tool

| Field          | Type          | Description                                                  |
| -------------- | ------------- | ------------------------------------------------------------ |
| `reply_id`     | `str`         | ID of the reply message                                      |
| `tool_call_id` | `str`         | ID of the corresponding tool call                            |
| `block_id`     | `str`         | Unique identifier of the data block                          |
| `media_type`   | `str`         | MIME type of the content                                     |
| `data`         | `str \| None` | Base64-encoded data (mutually exclusive with `url`)          |
| `url`          | `str \| None` | URL pointing to the content (mutually exclusive with `data`) |

#### ToolResultEndEvent — tool execution is complete

| Field          | Type              | Description                                                            |
| -------------- | ----------------- | ---------------------------------------------------------------------- |
| `reply_id`     | `str`             | ID of the reply message                                                |
| `tool_call_id` | `str`             | ID of the corresponding tool call                                      |
| `state`        | `ToolResultState` | Final state: `SUCCESS`, `ERROR`, `INTERRUPTED`, `DENIED`, or `RUNNING` |

---

### Model Call Events

#### ModelCallStartEvent — a model API call begins

| Field        | Type  | Description                    |
| ------------ | ----- | ------------------------------ |
| `reply_id`   | `str` | ID of the reply message        |
| `model_name` | `str` | Name of the model being called |

#### ModelCallEndEvent — a model API call completes

| Field           | Type  | Description                       |
| --------------- | ----- | --------------------------------- |
| `reply_id`      | `str` | ID of the reply message           |
| `input_tokens`  | `int` | Number of input tokens consumed   |
| `output_tokens` | `int` | Number of output tokens generated |

---

### Human-in-the-Loop Events

#### RequireUserConfirmEvent — agent pauses for user confirmation

| Field        | Type                  | Description                          |
| ------------ | --------------------- | ------------------------------------ |
| `reply_id`   | `str`                 | ID of the reply message              |
| `tool_calls` | `list[ToolCallBlock]` | Tool calls pending user confirmation |

#### RequireExternalExecutionEvent — agent pauses for external execution

| Field        | Type                  | Description                          |
| ------------ | --------------------- | ------------------------------------ |
| `reply_id`   | `str`                 | ID of the reply message              |
| `tool_calls` | `list[ToolCallBlock]` | Tool calls to be executed externally |

#### UserConfirmResultEvent — user provides confirmation results (input event)

| Field             | Type                  | Description                                     |
| ----------------- | --------------------- | ----------------------------------------------- |
| `reply_id`        | `str`                 | ID of the reply message                         |
| `confirm_results` | `list[ConfirmResult]` | Confirmation results for each pending tool call |

#### ExternalExecutionResultEvent — external system provides execution results (input event)

| Field               | Type                    | Description                               |
| ------------------- | ----------------------- | ----------------------------------------- |
| `reply_id`          | `str`                   | ID of the reply message                   |
| `execution_results` | `list[ToolResultBlock]` | Results returned by the external executor |

---

### One-shot Events

These events do **not** follow the start → delta → end pattern. The full payload arrives in a single event because it is known up-front rather than streamed.

#### HintBlockEvent — a `HintBlock` is injected into the agent's context

(e.g. a scheduled-task trigger, a team message, a result returned by an offloaded background tool)

| Field      | Type                                  | Description                                                                                                     |
| ---------- | ------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| `reply_id` | `str`                                 | ID of the reply message                                                                                         |
| `block_id` | `str`                                 | Unique identifier of the hint block                                                                             |
| `hint`     | `str \| list[TextBlock \| DataBlock]` | The hint payload — plain text or a list of multimodal blocks                                                    |
| `source`   | `str \| None`                         | Optional sender / origin tag (typically a small JSON object describing how the frontend should label this hint) |

#### CustomEvent — generic extensible event

Used by service-layer middleware to notify subscribers about state changes (task progress, team membership, permission updates, …) without polluting the core agent event enum.

| Field      | Type   | Description                                                |
| ---------- | ------ | ---------------------------------------------------------- |
| `reply_id` | `str`  | ID of the reply message                                    |
| `name`     | `str`  | The signal name (e.g. `"tasks_context"`, `"team_updated"`) |
| `value`    | `dict` | Arbitrary JSON-serialisable payload for this signal        |

---

### append_event(event) — message reconstruction method

`Msg.append_event(event)` applies a single `AgentEvent` to the message to incrementally rebuild its state. Effect per event type:

| Event Type                     | Effect on Msg                                                                 |
| ------------------------------ | ----------------------------------------------------------------------------- |
| `ReplyEndEvent`                | Sets `finished_at` timestamp                                                  |
| `TextBlockStartEvent`          | Appends a new empty `TextBlock`                                               |
| `TextBlockDeltaEvent`          | Concatenates `delta` to the block's text                                      |
| `DataBlockStartEvent`          | Appends a new empty `DataBlock`                                               |
| `DataBlockDeltaEvent`          | Concatenates `data` to the block's base64 content                            |
| `ThinkingBlockStartEvent`      | Appends a new empty `ThinkingBlock`                                           |
| `ThinkingBlockDeltaEvent`      | Concatenates `delta` to the block's thinking text                            |
| `ToolCallStartEvent`           | Appends a new `ToolCallBlock` with empty input                               |
| `ToolCallDeltaEvent`           | Concatenates `delta` to the tool call's input                                |
| `ToolResultStartEvent`         | Appends a new `ToolResultBlock` with empty output                            |
| `ToolResultTextDeltaEvent`     | Appends text to the tool result's output                                     |
| `ToolResultDataDeltaEvent`     | Appends a binary data block to the tool result's output                      |
| `ToolResultEndEvent`           | Sets the tool result's final `state`                                         |
| `HintBlockEvent`               | Appends a `HintBlock` to content (carrying the event's `hint` and `source`)  |
| `RequireUserConfirmEvent`      | Updates tool call states to `ASKING`                                         |
| `ExternalExecutionResultEvent` | Appends `ToolResultBlock`s to content                                        |

---

### TypeScript primitives — `@agentscope-ai/agentscope`

A TypeScript version of the message/event primitives is published on npm so frontends can reconstruct messages from the event stream with the same API.

Install:
```bash
pnpm install @agentscope-ai/agentscope
```

Import path: `@agentscope-ai/agentscope/message` (exports `AssistantMsg`, `ReplyStartEvent`, etc.).

- `new AssistantMsg({ name, content, id })` — constructor takes an options object.
- `msg.appendEvent(event)` — TS equivalent of `append_event`.
- Events carry a `type` discriminator string, e.g. `event.type === "REPLY_START"`.

---

## Configuration

There are no global config files for this unit; "configuration" here means the structural fields/options of the data types.

| Option / Field | Where | Type | Default | Controls |
| -------------- | ----- | ---- | ------- | -------- |
| `Msg.role` | `Msg` | `"user" \| "assistant" \| "system"` | (set by factory) | Determines which block types are allowed (enforced at construction). |
| `Msg.metadata` | `Msg` | `dict` | `{}` | Arbitrary key-value metadata attached to a message. |
| `get_text_content(separator)` | method | `str` | `"\n"` | Separator used to join multiple `TextBlock`s. |
| `ReplyStartEvent.role` | event | `str` | `"assistant"` | Agent role advertised at reply start. |
| `DataBlock` / `ToolResultDataDeltaEvent` `data` vs `url` | block/event | `str \| None` | — | `data` (base64) and `url` are **mutually exclusive** — supply exactly one. |
| `ToolResultEndEvent.state` | event | `ToolResultState` | — | Final tool outcome: `SUCCESS` / `ERROR` / `INTERRUPTED` / `DENIED` / `RUNNING`. |
| `HintBlock.source` | block/event | `str \| None` | `None` | Origin tag (small JSON) used by the frontend to label the hint. |
| `block_type` arg | `get_content_blocks` / `has_content_blocks` | `str` | — | Block selector, e.g. `"tool_call"`, `"tool_result"`, `"text"`, `"data"`, `"thinking"`. |

---

## Usage Patterns

### Creating messages with factories

```python
from agentscope.message import UserMsg, AssistantMsg, SystemMsg

# User message — text and optional images
user_msg = UserMsg(name="user", content="What's in this image?")

# User message with multimodal content
from agentscope.message import TextBlock, DataBlock, Base64Source
user_msg = UserMsg(
    name="user",
    content=[
        TextBlock(text="Describe this image:"),
        DataBlock(source=Base64Source(data="...", media_type="image/png")),
    ],
)

# System message — text only
system_msg = SystemMsg(name="system", content="You are a helpful assistant.")

# Assistant message — all block types allowed
assistant_msg = AssistantMsg(name="agent", content="Here is the result...")
```

### Accessing content

```python
# Get all text content
text = msg.get_text_content()

# Get all tool calls
tool_calls = msg.get_content_blocks("tool_call")

# Check if message has tool results
if msg.has_content_blocks("tool_result"):
    ...
```

### Reconstructing a message from an event stream

```python
from agentscope.message import Msg, AssistantMsg

msg = None

# Accumulate events into the message
async for event in agent.reply_stream(user_msg):
    if isinstance(event, ReplyStartEvent):
        # Create a new message when the reply starts
        msg = AssistantMsg(name=event.name, content=[], id=event.reply_id)
    else:
        # For all other events, append to the message to reconstruct its state
        msg.append_event(event)
```

### Streaming UI

```python
from agentscope.message import AssistantMsg, UserMsg
from agentscope.event import (
    ReplyStartEvent,
    TextBlockDeltaEvent,
    ToolCallStartEvent,
    ToolResultEndEvent,
    ReplyEndEvent,
)

msg = None

async for event in agent.reply_stream(UserMsg("user", "Fix the bug")):
    if isinstance(event, ReplyStartEvent):
        msg = AssistantMsg(name=event.name, content=[], id=event.reply_id)

    elif isinstance(event, TextBlockDeltaEvent):
        print(event.delta, end="", flush=True)

    elif isinstance(event, ToolCallStartEvent):
        print(f"\n[Calling {event.tool_call_name}...]")

    elif isinstance(event, ToolResultEndEvent):
        print(f"[Tool finished: {event.state}]")

    elif isinstance(event, ReplyEndEvent):
        print("\n[Done]")

    # Always accumulate into the message
    if msg is not None:
        msg.append_event(event)

# msg now contains the complete reply
```

### TypeScript reconstruction

```typescript
import { AssistantMsg, ReplyStartEvent } from "@agentscope-ai/agentscope/message";

let msg: AssistantMsg | null = null;

for await (const event of stream) {
    if (event.type === "REPLY_START") {
        msg = new AssistantMsg({ name: event.name, content: [], id: event.reply_id });
    } else {
        msg?.appendEvent(event);
    }
}
```

### Event lifecycle order (per content block)

Events follow a **start → delta → end** pattern per content block. Typical reply ordering:

1. `ReplyStartEvent`
2. Reasoning phase: `ModelCallStartEvent` → (`TextBlockStart/Delta×N/End`, `DataBlockStart/Delta×N/End`, `ToolCallStart/Delta×N/End`) → `ModelCallEndEvent`
3. Acting phase: `ToolResultStartEvent` → `ToolResultTextDeltaEvent×N` / `ToolResultDataDeltaEvent×N` → `ToolResultEndEvent`
4. `ReplyEndEvent`

Correlation keys: all events in a reply share `reply_id`; `block_id` correlates text/thinking/data block events; `tool_call_id` correlates a tool call with its tool result.

---

## Gotchas & Version Notes

- **One reply = one message.** A full `reply` cycle (reasoning + acting until a final response) produces exactly one assistant `Msg`. The complete message state must always be recoverable from the event stream alone.
- **Role constraints are enforced at construction — not lazily.** `user` → only `TextBlock`/`DataBlock`; `system` → only `TextBlock`; `assistant` → all block types. Constructing a message that violates this will fail.
- **Prefer the factory functions** (`UserMsg`, `AssistantMsg`, `SystemMsg`) over manually constructing `Msg` with a raw `role` — they set the correct role and auto-wrap a plain `str` into a `TextBlock`.
- **`data` and `url` are mutually exclusive** in `ToolResultDataDeltaEvent` (and `DataBlock` sources) — supply exactly one, never both.
- **Always accumulate every event** (not only the ones you render) via `append_event` so the reconstructed `Msg` is complete. In the streaming-UI pattern, `msg.append_event(event)` is called unconditionally for all events after the message is created on `ReplyStartEvent`.
- **`ReplyStartEvent` is special:** it must create the message (using `event.reply_id` as the `Msg` `id` and `event.name` as the name); it is the only event not appended via `append_event` in the reconstruction examples.
- **Input events vs output events:** `UserConfirmResultEvent` and `ExternalExecutionResultEvent` are *input* events (sent into the agent), unlike the streaming output events.
- **`RequireUserConfirmEvent` sets tool call state to `ASKING`** when applied via `append_event`; resolve it with `UserConfirmResultEvent` carrying `list[ConfirmResult]`.
- **`HintBlock` is persisted and replayable:** applying `HintBlockEvent` appends a `HintBlock` to content so out-of-band hints survive in the saved message. Use `source` to tag origin for the frontend.
- **`CustomEvent` is the extension point** for service-layer signals (task progress, team updates, permission changes); use it instead of adding entries to the core agent event enum.
- **Use the npm package `@agentscope-ai/agentscope`** (TypeScript) for client-side reconstruction with `appendEvent`; events use an uppercase snake-case `type` discriminator (e.g. `"REPLY_START"`), not Python class names.
- **`ToolResultState` valid values:** `SUCCESS`, `ERROR`, `INTERRUPTED`, `DENIED`, `RUNNING` — do not invent other states.
- Import boundaries: messages/blocks come from `agentscope.message`; events come from `agentscope.event`.

> Note: This file documents the AgentScope v2 docs (docs.agentscope.io/v2) against installed package `agentscope` 1.0.20. The page was fetched successfully and was not empty; no 404 encountered.
