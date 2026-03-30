# Context Management

## Overview

Imagine the LLM's context window as a **backpack with limited capacity** 🎒. Every conversation turn, every tool call result adds something to the backpack. As the conversation goes on, the backpack gets fuller and fuller...

**Context management** is a set of mechanisms that help you "manage your backpack", ensuring the AI can work continuously and efficiently.

> The context management mechanism is inspired by [OpenClaw](https://github.com/openclaw/openclaw) and implemented via **ReMeLight** from [ReMe](https://github.com/agentscope-ai/ReMe).

### How It Works — Summary

CoPaw context management uses two parallel offload paths to handle the limited context window:

| Mechanism                          | Triggered When                        | Offload Target            | What Stays in Context                    |
| ---------------------------------- | ------------------------------------- | ------------------------- | ---------------------------------------- |
| **Tool result offload**            | Tool output exceeds byte threshold    | `tool_result/{uuid}.txt`  | Snippet + file path reference            |
| **Conversation compact + archive** | Context token count exceeds threshold | `dialog/YYYY-MM-DD.jsonl` | `compact_summary` (summary + path guide) |

**Before each inference turn**, `MemoryCompactionHook` runs in order:

```mermaid
flowchart LR
    A[Before each turn] --> B[1 Tool result offload]
    B --> C[2 Token threshold check]
    C -->|Under limit| D[Proceed normally]
    C -->|Over limit| E[3 Compact old messages\ngenerate compact_summary]
    E --> F[4 Archive raw messages\nwrite to dialog/]
    F --> D
```

- **No data loss**: Compacted raw conversations are saved in `dialog/`, tool outputs in `tool_result/` — the Agent can always retrieve them via `read_file`
- **Context continuity**: `compact_summary` retains a structured summary + dialog path guide so the Agent never loses context
- **Automatic**: Triggers without manual intervention; `/compact` can also trigger it manually

## Context Structure

### In-Memory Data Structure

CoPaw's context consists of two components:

```mermaid
flowchart TD
    A[Context] --> B[compact_summary optional]
    B --> C[Dialog path guide<br>dialog/YYYY-MM-DD.jsonl N lines]
    B --> D[Structured history summary<br>Goal / Constraints / Progress<br>KeyDecisions / NextSteps]
    A --> E[messages full dialogue history]
```

| Component                    | Description                                                                |
| ---------------------------- | -------------------------------------------------------------------------- |
| **compact_summary**          | Generated after compaction; contains two parts (see below)                 |
| ↳ Dialog path guide          | Points to raw conversation data in `dialog/YYYY-MM-DD.jsonl` for reference |
| ↳ Structured history summary | Goal / Constraints / Progress / KeyDecisions / NextSteps                   |
| **messages**                 | Current conversation context (full message list)                           |

### File System Cache

Data evicted from the context is offloaded to the file system, keeping it traceable:

| Path                      | Contents                                                       |
| ------------------------- | -------------------------------------------------------------- |
| `dialog/YYYY-MM-DD.jsonl` | Compacted raw conversation messages, appended chronologically  |
| `tool_result/{uuid}.txt`  | Full text of long tool call results; auto-cleaned after N days |

### Message Zone Division

```mermaid
graph LR
    A[System Prompt] -->|Always retained| B[Compactable Zone<br>Compactable Messages]
    B -->|Compress when exceeded| C[Reserved Zone<br>Recent Messages]
```

| Zone                 | Description                                      | Handling                                                      |
| -------------------- | ------------------------------------------------ | ------------------------------------------------------------- |
| **System Prompt**    | The AI's "role definition" and base instructions | Always retained, never compacted                              |
| **Compactable Zone** | Historical conversation messages                 | Token counted; compacted into summary when threshold exceeded |
| **Reserved Zone**    | Most recent N messages                           | Kept as-is, ensuring context continuity                       |

### Structure Example

```
┌─────────────────────────────────────────┐
│ System Prompt (Fixed)                    │  ← Always retained
│ "You are an AI assistant..."             │
├─────────────────────────────────────────┤
│ compact_summary (Optional)               │  ← Generated after compaction
│  - [Dialog guide] dialog/2025-01-15.jsonl│
│  - Goal: Build user login system         │
│  - Progress: Login API completed...      │
├─────────────────────────────────────────┤
│ Compactable Zone                         │  ← Compacted when exceeded
│ [Message 1] User: Help me build login    │
│ [Message 2] Assistant: Sure, I'll...     │
│ [Message 3] Tool call result...          │
│ ...                                      │
├─────────────────────────────────────────┤
│ Reserved Zone                            │  ← Always retained
│ [Message N-2] User: Add registration     │
│ [Message N-1] Assistant: Sure...         │
│ [Message N] User: Done!                  │
└─────────────────────────────────────────┘
```

## Management Mechanism

### Architecture Overview

```mermaid
graph LR
    Agent[Agent] -->|Before each inference| Hook[MemoryCompactionHook]
    Hook --> TC[compact_tool_result<br>Compress tool output]
    TC --> CC[check_context<br>Token counting]
    CC -->|Exceeds limit| CM[compact_memory<br>Generate summary]
```

### Related Code

- [MemoryCompactionHook](https://github.com/agentscope-ai/CoPaw/blob/main/src/copaw/agents/hooks/memory_compaction.py)
- [compact_tool_result](https://github.com/agentscope-ai/ReMe/blob/v0.3.1.6/reme/memory/file_based/components/tool_result_compactor.py)
- [check_context](https://github.com/agentscope-ai/ReMe/blob/v0.3.1.6/reme/memory/file_based/components/context_checker.py)
- [compact_memory](https://github.com/agentscope-ai/ReMe/blob/v0.3.1.6/reme/memory/file_based/components/compactor.py)

### Execution Flow

```mermaid
flowchart LR
    M[messages] --> TC[ToolCallResultCompact<br>Offload long tool outputs]
    TC --> CC[ContextChecker<br>Token counting]
    CC --> D{Token > Threshold?}
    D -->|No| K[Proceed normally]
    D -->|Yes| E[Keep recent X% tokens]
    E --> CM[Compactor<br>Compact old messages into summary]
    CM --> SD[SaveDialog<br>Offload compacted messages to<br>dialog/YYYY-MM-DD.jsonl]
    SD --> R[Update compact_summary + clear old messages]
```

**Execution Order**:

1. `ToolCallResultCompact` — Offload long tool outputs to `tool_result/` (if enabled)
2. `ContextChecker` — Determine if token count exceeds threshold
3. `Compactor` — Compress old messages into a structured summary (`compact_memory`)
4. `SaveDialog` — Persist the compacted raw messages to `dialog/YYYY-MM-DD.jsonl`

## Compaction Mechanism

When the context approaches its limit, CoPaw automatically triggers compaction, condensing old conversations into a structured summary.

### 1. compact_tool_result — Tool Result Compaction

When `tool_result_compact.enabled` is on (default `true`), different byte thresholds are applied based on how recent a message is:

```mermaid
flowchart LR
    A[Tool Call Result] --> B{Within recent_n?}
    B -->|Yes| C[Low truncation<br>recent_max_bytes<br>Save full text to tool_result/uuid.txt<br>Keep snippet + file ref in message]
    B -->|No| D[High truncation<br>old_max_bytes<br>Reference existing file<br>More aggressive truncation]
    C --> E[Context]
    D --> E
```

| Message type           | Threshold          | Default | Behavior                                        |
| ---------------------- | ------------------ | ------- | ----------------------------------------------- |
| Most recent `recent_n` | `recent_max_bytes` | `50000` | Preserve more content; save full text to file   |
| Older messages         | `old_max_bytes`    | `3000`  | Aggressive truncation; reuse existing file path |

**Tool-specific behavior:**

- **Browser-use type tools**: On first call, full content is saved to `tool_result/uuid.txt`, message keeps snippet + file reference with a "read from line N" hint; secondary truncation applies once the message falls outside `recent_n`
- **read_file tool**: No truncation or file save within `recent_n` (content is already an external file); beyond `recent_n`, truncated and saved to `tool_result/`
- Files older than `retention_days` are automatically cleaned up

### 2. check_context — Context Check

Determines if context exceeds limits based on token counting, automatically splitting messages into "to compact" and "to keep" groups.

```mermaid
graph LR
    M[messages] --> H[Token counting]
    H --> C{total > threshold?}
    C -->|No| K[Return all messages]
    C -->|Yes| S[Keep from tail backwards<br>reserve tokens]
    S --> CP[messages_to_compact<br>Early messages]
    S --> KP[messages_to_keep<br>Recent messages]
    S --> V{is_valid<br>Tool call alignment?}
```

- **Core Logic**: Reserve `memory_compact_reserve` tokens from the tail backwards, marking excess as to-be-compacted
- **Integrity Guarantee**: Does not split user-assistant conversation pairs or tool_use/tool_result pairs

### 3. compact_memory — Conversation Compaction

Uses ReActAgent to compress historical conversations into a **structured context summary**:

```mermaid
graph LR
    M[messages] --> H[format_msgs_to_str]
    H --> A[ReActAgent<br>reme_compactor]
    P[previous_summary] -->|Incremental update| A
    A --> S[Structured summary]
```

### 4. Manual Compaction (/compact Command)

Proactively trigger compaction:

```
/compact
```

After execution, you'll see:

```
**Compact Complete!**

- Messages compacted: 12
**Compressed Summary:**
<compacted summary content>
```

Response breakdown:

- 📊 **Messages compacted** - How many messages were compacted
- 📝 **Compressed Summary** - The generated summary content

## Compaction Summary Structure

`compact_summary` consists of two parts: a **dialog path guide** and a **structured history summary**.

### Dialog Path Guide

Points to compacted raw conversation data in `dialog/YYYY-MM-DD.jsonl` (written chronologically; recommended to read from the end backwards). The Agent can use the `read_file` tool to review historical details without keeping raw messages in the active context.

### Structured History Summary

```mermaid
graph TB
    A[Structured History Summary] --> B[Goal]
    A --> C[Constraints]
    A --> D[Progress]
    A --> E[Key Decisions]
    A --> F[Next Steps]
    A --> G[Critical Context]
```

| Field                | Content                                 | Example                                        |
| -------------------- | --------------------------------------- | ---------------------------------------------- |
| **Goal**             | What the user wants to accomplish       | "Build a user login system"                    |
| **Constraints**      | Requirements and preferences            | "Use TypeScript, no frameworks"                |
| **Progress**         | Completed / in-progress / blocked tasks | "Login API done, registration API in progress" |
| **Key Decisions**    | Decisions made and their rationale      | "Chose JWT over Sessions for statelessness"    |
| **Next Steps**       | What to do next                         | "Implement password reset feature"             |
| **Critical Context** | Data needed to continue work            | "Main file is at src/auth.ts"                  |

- **Incremental Update**: When `previous_summary` is provided, new conversations are automatically merged with the old summary
- **Information Preservation**: Compaction preserves exact file paths, function names, and error messages, ensuring seamless context transitions

## Configuration

Configuration is located in `~/.copaw/config.json` under `agents.running`:

**`running` top-level fields:**

| Parameter          | Default  | Description                        |
| ------------------ | -------- | ---------------------------------- |
| `max_input_length` | `131072` | Model context window size (tokens) |

**`running.context_compact` fields:**

| Parameter                     | Default | Description                                                                                    |
| ----------------------------- | ------- | ---------------------------------------------------------------------------------------------- |
| `context_compact_enabled`     | `true`  | Whether to enable automatic context compaction                                                 |
| `memory_compact_ratio`        | `0.75`  | Threshold ratio for triggering compaction, triggers when `max_input_length × ratio` is reached |
| `memory_reserve_ratio`        | `0.1`   | Ratio of recent messages to keep during compaction, keeps `max_input_length × ratio` tokens    |
| `compact_with_thinking_block` | `true`  | Whether to include thinking blocks during compaction                                           |

**`running.tool_result_compact` fields:**

| Parameter          | Default | Description                                                         |
| ------------------ | ------- | ------------------------------------------------------------------- |
| `enabled`          | `true`  | Whether to compress long tool outputs                               |
| `recent_n`         | `2`     | Number of recent messages to apply `recent_max_bytes` threshold to  |
| `old_max_bytes`    | `3000`  | Byte threshold for older tool result messages                       |
| `recent_max_bytes` | `50000` | Byte threshold for the most recent `recent_n` tool result messages  |
| `retention_days`   | `5`     | Days to retain cached tool output files (auto-cleaned after expiry) |

**Calculation Relationships:**

- `memory_compact_threshold` = `max_input_length × memory_compact_ratio` (threshold for triggering compaction)
- `memory_compact_reserve` = `max_input_length × memory_reserve_ratio` (tokens of recent messages to keep)

**Example Configuration:**

```json
{
  "agents": {
    "running": {
      "max_input_length": 128000,
      "context_compact": {
        "memory_compact_ratio": 0.7,
        "memory_reserve_ratio": 0.1
      },
      "tool_result_compact": {
        "enabled": true,
        "recent_n": 3,
        "old_max_bytes": 3000,
        "recent_max_bytes": 50000
      }
    }
  }
}
```
