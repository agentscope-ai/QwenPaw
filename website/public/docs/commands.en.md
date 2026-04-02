# Magic Commands

Magic commands are special instructions prefixed with `/` that let you **directly control conversation state** without waiting for the AI to interpret your intent.

---

## Conversation Management Commands

Commands for controlling conversation context.

| Command    | Wait   | Compressed Summary | Long-term Memory   | Response Content              |
| ---------- | ------ | ------------------ | ------------------ | ----------------------------- |
| `/compact` | ⏳ Yes | 📦 Generate new    | ✅ Background save | ✅ Compact complete + Summary |
| `/new`     | ⚡ No  | 🗑️ Clear           | ✅ Background save | ✅ New conversation prompt    |
| `/clear`   | ⚡ No  | 🗑️ Clear           | ❌ No save         | ✅ History cleared prompt     |

---

### /compact - Compress Current Conversation

Manually trigger conversation compaction, condensing all current messages into a summary (**requires waiting**), while saving to long-term memory in the background.

```
/compact
```

**Example response:**

```
**Compact Complete!**

- Messages compacted: 12
**Compressed Summary:**
User requested help building a user authentication system, login endpoint implementation completed...
- Summary task started in background
```

> 💡 Unlike auto-compaction, `/compact` compresses **all** current messages, not just the portion exceeding the threshold.

---

### /new - Clear Context and Save Memory

**Immediately clear the current context** and start a fresh conversation. History is saved to long-term memory in the background.

```
/new
```

**Example response:**

```
**New Conversation Started!**

- Summary task started in background
- Ready for new conversation
```

---

### /clear - Clear Context (Without Saving Memory)

**Immediately clear the current context**, including message history and compressed summaries. Nothing is saved to long-term memory.

```
/clear
```

**Example response:**

```
**History Cleared!**

- Compressed summary reset
- Memory is now empty
```

> ⚠️ **Warning**: `/clear` is **irreversible**! Unlike `/new`, cleared content will not be saved.

---

## Plan commands

Structured multi-step work uses **plan mode**. The agent is **not** prompted to create a plan on every message; you start planning explicitly.

| Form | Behavior |
| ---- | -------- |
| `/plan` | Turns on plan mode if needed, then shows whether a plan exists and lists subtasks (or hints to use `/plan <description>`). |
| `/plan <description>` | Treated as a normal chat message (prefix stripped): the agent receives an explicit request to create a plan for the task. |

**Example:**

```
/plan Refactor the auth module and add tests
```

**Backward compatibility:** Older flows that relied on the model seeing a default “no plan” hint on every turn no longer apply; use `/plan` or the console Plan panel to begin planning.

---

## Conversation Debugging Commands

Commands for viewing and managing conversation history.

| Command         | Response Content              |
| --------------- | ----------------------------- |
| `/history`      | 📋 Message list + Token stats |
| `/message`      | 📄 Specified message details  |
| `/compact_str`  | 📝 Compressed summary content |
| `/dump_history` | 📁 Exported history file path |
| `/load_history` | ✅ History load result        |

---

### /history - View Current Conversation History

Display a list of all uncompressed messages in the current conversation, along with detailed **context usage information**.

```
/history
```

**Example response:**

```
**Conversation History**

- Total messages: 3
- Estimated tokens: 1256
- Max input length: 128000
- Context usage: 0.98%
- Compressed summary tokens: 128

[1] **user** (text_tokens=42)
    content: [text(tokens=42)]
    preview: Write me a Python function...

[2] **assistant** (text_tokens=256)
    content: [text(tokens=256)]
    preview: Sure, let me write a function for you...

[3] **user** (text_tokens=28)
    content: [text(tokens=28)]
    preview: Can you add error handling?

---

- Use /message <index> to view full message content
- Use /compact_str to view full compact summary
```

> 💡 **Tip**: Use `/history` frequently to monitor your context usage.
>
> When `Context usage` approaches 75%, the conversation is about to trigger auto-`compact`.
>
> If context exceeds the maximum limit, please report the model and `/history` logs to the community, then use `/compact` or `/new` to manage context.
>
> Token calculation logic: [ReMeInMemoryMemory implementation](https://github.com/agentscope-ai/ReMe/blob/v0.3.0.6b2/reme/memory/file_based/reme_in_memory_memory.py#L122).

---

### /message - View Single Message

View detailed content of a specific message by index.

```
/message <index>
```

**Parameters:**

- `index` - Message index number (starting from 1)

**Example:**

```
/message 1
```

**Output:**

```
**Message 1/3**

- **Timestamp:** 2024-01-15 10:30:00
- **Name:** user
- **Role:** user
- **Content:**
Write me a Python function that implements quicksort
```

---

### /compact_str - View Compressed Summary

Display the current compressed summary content.

```
/compact_str
```

**Example response (when summary exists):**

```
**Compressed Summary**

User requested help building a user authentication system, login endpoint implementation completed...
```

**Example response (when no summary):**

```
**No Compressed Summary**

- No summary has been generated yet
- Use /compact or wait for auto-compaction
```

---

### /dump_history - Export Conversation History

Save current conversation history (including compressed summary) to a JSONL file for debugging and backup.

```
/dump_history
```

**Example response:**

```
**History Dumped!**

- Messages saved: 15
- Has summary: True
- File: `/path/to/workspace/debug_history.jsonl`
```

> 💡 **Tip**: The exported file can be used with `/load_history` to restore conversation history, or for debugging analysis.

---

### /load_history - Load Conversation History

Load conversation history from a JSONL file into current memory. **Existing memory will be cleared first**.

```
/load_history
```

**Example response:**

```
**History Loaded!**

- Messages loaded: 15
- Has summary: True
- File: `/path/to/workspace/debug_history.jsonl`
- Memory cleared before loading
```

**Notes:**

- File source: Loaded from `debug_history.jsonl` in the workspace directory
- Maximum load: 10,000 messages
- If the first message in the file contains a compressed summary marker, the summary will be restored automatically
- Current memory is **cleared before loading** — make sure to backup important content

> ⚠️ **Warning**: `/load_history` clears current memory before loading. Existing conversation will be lost!

---

## System Control Commands

Commands for controlling and monitoring CoPaw's runtime status. These commands execute directly without going through the Agent.

Send `/daemon <subcommand>` or short names (e.g., `/status`) in chat, or run `copaw daemon <subcommand>` from the terminal.

| Command                             | Description                                                                             | Chat | Terminal |
| ----------------------------------- | --------------------------------------------------------------------------------------- | ---- | -------- |
| `/stop`                             | Immediately terminate the running task in current session                               | ✅   | ❌       |
| `/stop session=<session_id>`        | Terminate task in specified session                                                     | ✅   | ❌       |
| `/daemon status` or `/status`       | Show runtime status (config, working directory, memory service)                         | ✅   | ✅       |
| `/daemon restart` or `/restart`     | Zero-downtime reload (chat); prints instructions (terminal)                             | ✅   | ✅       |
| `/daemon reload-config`             | Re-read and validate configuration file                                                 | ✅   | ✅       |
| `/daemon version`                   | Version number, working directory, and log path                                         | ✅   | ✅       |
| `/daemon logs` or `/daemon logs 50` | View last N lines of log (default 100, max 2000, from `copaw.log` in working directory) | ✅   | ✅       |
| `/daemon approve`                   | Approve pending tool execution (tool-guard scenario)                                    | ✅   | ❌       |

---

### /stop - Stop Task

Immediately terminate the task currently executing in the session. Highest priority command that processes concurrently even when tasks are running.

**Usage:**

```
/stop                       # Stop current session's task
/stop session=<session_id>  # Stop task in specified session
```

> ⚠️ **Warning**: `/stop` immediately terminates the task, which may result in partial data loss.

---

### /daemon status or /status - View Runtime Status

Display current runtime status, including configuration, working directory, and memory service status.

**Usage:**

```
/status                    # In chat
copaw daemon status        # From terminal
```

---

### /daemon restart or /restart - Zero-Downtime Reload

When used in chat, performs zero-downtime reload: reloads channels, cron, and MCP configurations without interrupting the process. Useful for applying channel or MCP configuration changes.

**Usage:**

```
/restart                   # In chat
copaw daemon restart       # From terminal (prints instructions only)
```

> 💡 **Tip**: After modifying channel or MCP configuration, use `/daemon reload-config` first to verify correctness, then use `/daemon restart` to apply changes.

---

### /daemon reload-config - Reload Configuration File

Re-read and validate the configuration file, but does not reload runtime components (channels, cron, MCP). Useful for verifying configuration file changes.

**Usage:**

```
/daemon reload-config           # In chat
copaw daemon reload-config      # From terminal
```

---

### /daemon version - Version Information

Display CoPaw version number, working directory path, and log file path.

**Usage:**

```
/daemon version            # In chat
copaw daemon version       # From terminal
```

---

### /daemon logs - View Logs

View the last N lines of `copaw.log` in the working directory. Default 100 lines, maximum 2000 lines.

**Usage:**

```
/daemon logs               # Default 100 lines
/daemon logs 50            # Specify 50 lines
copaw daemon logs -n 200   # From terminal, specify 200 lines
```

> 💡 **Tip**: For large log files, this command only reads the last 512KB from the end of the file to ensure fast response times.

---

### /daemon approve - Approve Tool Execution

Quickly approve pending tool execution. When tool execution requires manual approval (tool-guard scenario), use this command to approve.

**Usage:**

```
/daemon approve            # In chat
```

> 💡 **Tip**: This command only works in chat. When the Agent prompts for tool execution approval, send this command to quickly approve.

---

### Terminal Usage

All daemon commands support terminal usage (except `/stop` and `/daemon approve` which only work in chat):

```bash
copaw daemon status
copaw daemon restart
copaw daemon reload-config
copaw daemon version
copaw daemon logs -n 50
```

**Multi-agent support:** All terminal commands support the `--agent-id` parameter (defaults to `default`).

```bash
copaw daemon status --agent-id abc123
copaw daemon version --agent-id abc123
```
