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

Optionally, add an extra instruction to guide what the summary should keep or remove:

```
/compact keep requirements, decisions, and pending tasks; remove debug logs and tool-call details
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
> 💡 The extra instruction only applies to this manual `/compact` run. Auto-compaction behavior is unchanged.

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

## Conversation Debugging Commands

Commands for viewing and managing conversation history.

| Command             | Response Content              |
| ------------------- | ----------------------------- |
| `/history`          | 📋 Message list + Token stats |
| `/message`          | 📄 Specified message details  |
| `/compact_str`      | 📝 Compressed summary content |
| `/summarize_status` | 📊 Summary task status        |
| `/dump_history`     | 📁 Exported history file path |
| `/load_history`     | ✅ History load result        |

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

### /summarize_status - View Summary Task Status

Display the running status of all background summary tasks, including task ID, start time, and execution results.

```
/summarize_status
```

**Example response:**

```
**Summary Task Status**

- **task-001**
  - Start: 2024-01-15 10:30:00
  - Status: completed
  - Result: User requested help building a user authentication system...
- **task-002**
  - Start: 2024-01-15 10:35:00
  - Status: failed
  - Error: Summary generation timeout
```

> 💡 Using `/compact` or `/new` automatically starts a summary task in the background. Use this command to check its execution status.

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

## Skill Chat Commands

These commands let you inspect skill status in chat and force the agent to use
a specific skill.

- `/skills` lists skills available in the current channel in a compact format.
- `/<skill_name>` shows detailed information for that skill, including its
  description and local path.
- `/<skill_name> <input>` forces the agent to use `skill_name` to solve the
  input, usually a task.
- `/[skill_name]` is also supported as an alternate form.

Notes:

- `skill_name` must match the skill command name shown in `/skills`.
- These slash commands only work for skills that are enabled and routed to the
  current channel.

---

## Model Management Commands

Commands for managing and switching AI models. These commands execute directly without going through the Agent.

| Command                          | Description                                      | Chat |
| -------------------------------- | ------------------------------------------------ | ---- |
| `/model`                         | Show current active model                        | ✅   |
| `/model -h` or `/model help`     | Show help information                            | ✅   |
| `/model list`                    | List all available models                        | ✅   |
| `/model <provider>:<model>`      | Switch to specified model                        | ✅   |
| `/model reset`                   | Reset to global default model                    | ✅   |
| `/model info <provider>:<model>` | Show detailed information about a specific model | ✅   |

---

### /model - Show Current Model

Display the currently active model for this agent.

**Usage:**

```
/model
```

**Example response:**

```
**Current Model**

Provider: `openai`
Model: `gpt-4o` ✓

Use `/model list` to see all available models.
```

---

### /model -h or /model help - Show Help

Display help information for all `/model` commands.

**Usage:**

```
/model -h
/model --help
/model help
```

**Example response:**

```
**Model Management Commands**

Manage and switch AI models for the current agent.

**Available Commands:**

`/model` - Show current active model
`/model list` - List all available models
`/model <provider>:<model>` - Switch to specified model
`/model reset` - Reset to global default model
`/model info <provider>:<model>` - Show model information
`/model help` or `/model -h` - Show this help message

**Examples:**

`/model` - Show current model
`/model list` - List all models
`/model openai:gpt-4o` - Switch to GPT-4o
`/model reset` - Reset to global default
`/model info openai:gpt-4o` - Show GPT-4o information

**Capability Indicators:**

🖼️ - Supports image input
🎥 - Supports video input
```

---

### /model list - List All Models

Display all configured providers and their available models. The currently active model is marked with **[ACTIVE]**.

**Usage:**

```
/model list
```

**Example response:**

```
**Available Models**

**OpenAI** (`openai`)
  - `gpt-4o` 🖼️ **[ACTIVE]**
  - `gpt-4o-mini` 🖼️
  - `gpt-3.5-turbo`
  - `my-custom-model` *(user-added)*

**Anthropic** (`anthropic`)
  - `claude-3-5-sonnet-20241022`
  - `claude-3-opus-20240229`

**Google** (`gemini`)
  - `gemini-2.0-flash-exp` 🖼️🎥

---
Total: 3 provider(s), 8 model(s)

Use `/model <provider>:<model>` to switch models.
Example: `/model openai:gpt-4o`
```

**Indicators:**

- 🖼️ - Supports image input
- 🎥 - Supports video input
- _(user-added)_ - User-added model (via `qwenpaw models add-model` command)

---

### /model <provider>:<model> - Switch Model

Switch the current agent to use a different model.

**Usage:**

```
/model <provider>:<model>
```

**Examples:**

```
/model openai:gpt-4o
/model anthropic:claude-3-5-sonnet-20241022
/model gemini:gemini-2.0-flash-exp
```

**Example response:**

```
**Model Switched**

Provider: `anthropic`
Model: `claude-3-5-sonnet-20241022`

The new model will be used for subsequent messages.
```

> 💡 **Tip**: Model changes only affect the current agent. Other agents continue using their configured models.

---

### /model reset - Reset to Global Default

Reset the current agent's model to the global default model configured in the web UI.

**Usage:**

```
/model reset
```

**Example response:**

```
**Model Reset**

Agent model has been reset to global default:

Provider: `openai`
Model: `gpt-4o`

The global default model will be used for subsequent messages.
```

> 💡 **Tip**: Use this command to revert agent-specific model overrides.

---

### /model info - Show Model Information

Display detailed information about a specific model, including capabilities and current status.

**Usage:**

```
/model info <provider>:<model>
```

**Examples:**

```
/model info openai:gpt-4o
/model info anthropic:claude-3-5-sonnet-20241022
```

**Example response:**

```
**Model Information**

**Provider:** `openai` (OpenAI)
**Model ID:** `gpt-4o`
**Model Name:** GPT-4o
**Capabilities:** 🖼️ Image, 🎨 Multimodal
**Probe Source:** documentation

**Status:** ✓ Currently active

---
Use `/model openai:gpt-4o` to switch to this model.
```

---

## System Control Commands

Commands for controlling and monitoring QwenPaw's runtime status. These commands execute directly without going through the Agent.

Send `/daemon <subcommand>` or short names (e.g., `/status`) in chat, or run `qwenpaw daemon <subcommand>` from the terminal.

| Command                             | Description                                                                               | Chat | Terminal |
| ----------------------------------- | ----------------------------------------------------------------------------------------- | ---- | -------- |
| `/stop`                             | Immediately terminate the running task in current session                                 | ✅   | ❌       |
| `/stop session=<session_id>`        | Terminate task in specified session                                                       | ✅   | ❌       |
| `/daemon status` or `/status`       | Show runtime status (config, working directory, memory service)                           | ✅   | ✅       |
| `/daemon restart` or `/restart`     | Zero-downtime reload (chat); prints instructions (terminal)                               | ✅   | ✅       |
| `/daemon reload-config`             | Re-read and validate configuration file                                                   | ✅   | ✅       |
| `/daemon version`                   | Version number, working directory, and log path                                           | ✅   | ✅       |
| `/daemon logs` or `/daemon logs 50` | View last N lines of log (default 100, max 2000, from `qwenpaw.log` in working directory) | ✅   | ✅       |
| `/approval approve [request_id]`    | Approve pending tool execution (or queue head if no ID)                                   | ✅   | ❌       |
| `/approval deny [request_id]`       | Deny pending tool execution with optional reason                                          | ✅   | ❌       |
| `/approval list`                    | List all pending approval requests                                                        | ✅   | ❌       |
| `/approval cancel <request_id>`     | Cancel a specific approval request                                                        | ✅   | ❌       |
| `/approve`                          | Shorthand for `/approval approve`                                                         | ✅   | ❌       |
| `/deny`                             | Shorthand for `/approval deny`                                                            | ✅   | ❌       |

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
qwenpaw daemon status        # From terminal
```

---

### /daemon restart or /restart - Zero-Downtime Reload

When used in chat, performs zero-downtime reload: reloads channels, cron, and MCP configurations without interrupting the process. Useful for applying channel or MCP configuration changes.

**Usage:**

```
/restart                   # In chat
qwenpaw daemon restart       # From terminal (prints instructions only)
```

> 💡 **Tip**: After modifying channel or MCP configuration, use `/daemon reload-config` first to verify correctness, then use `/daemon restart` to apply changes.

---

### /daemon reload-config - Reload Configuration File

Re-read and validate the configuration file, but does not reload runtime components (channels, cron, MCP). Useful for verifying configuration file changes.

**Usage:**

```
/daemon reload-config           # In chat
qwenpaw daemon reload-config      # From terminal
```

---

### /daemon version - Version Information

Display QwenPaw version number, working directory path, and log file path.

**Usage:**

```
/daemon version            # In chat
qwenpaw daemon version       # From terminal
```

---

### /daemon logs - View Logs

View the last N lines of `qwenpaw.log` in the working directory. Default 100 lines, maximum 2000 lines.

**Usage:**

```
/daemon logs               # Default 100 lines
/daemon logs 50            # Specify 50 lines
qwenpaw daemon logs -n 200   # From terminal, specify 200 lines
```

> 💡 **Tip**: For large log files, this command only reads the last 512KB from the end of the file to ensure fast response times.

---

### /approval - Tool Execution Approval Commands

Manage tool guard approval requests. When `approval_level` is set to `STRICT` or `SMART`, tools with CRITICAL or HIGH findings enter a pending-approval flow. Use these commands to approve, deny, list, or cancel requests.

**Usage:**

```
/approval approve [request_id]           # Approve specific request or queue head
/approval deny [request_id] [reason]     # Deny with optional reason
/approval list                           # List pending approvals (current session)
/approval list --all                     # List all pending approvals (all sessions)
/approval cancel <request_id>            # Cancel a specific request
```

**Shorthands:**

```
/approve                                 # Same as /approval approve
/approve <request_id>                    # Same as /approval approve <request_id>
/deny                                    # Same as /approval deny
/deny <request_id> <reason>              # Same as /approval deny <request_id> <reason>
```

> `/approval list` shows pending approvals for the current session (including child sessions). Use `--all` or `-a` to see all sessions for this agent.

---

### Terminal Usage

All daemon commands support terminal usage (except `/stop` and `/approval` which only work in chat):

```bash
qwenpaw daemon status
qwenpaw daemon restart
qwenpaw daemon reload-config
qwenpaw daemon version
qwenpaw daemon logs -n 50
```

**Multi-agent support:** All terminal commands support the `--agent-id` parameter (defaults to `default`).

```bash
qwenpaw daemon status --agent-id abc123
qwenpaw daemon version --agent-id abc123
```

---

## Goal Mode — Persistent Goal Loop

Set an objective, and the Agent works autonomously across multiple turns until it is done. Suitable for any clear-objective task.

```
/goal <task description>
```

For a full guide, see [Loop Engineering](./loop-engineering).

---

## Mission Mode — Multi-Agent Autonomous Execution

Decompose large tasks into user stories and complete them through a **master → worker → verifier** pipeline with context isolation.

```
/mission <task description>
/mission <task> --max-iterations 30 --verify "pytest tests/"
/mission status             # check progress
/mission list               # list all missions
```

For a full guide, see [Loop Engineering](./loop-engineering).

---

## Proactive Mode - Proactive Notification Mode

Proactive Mode is an intelligent feature that allows the AI agent to actively analyze the user's current session context and screen activities after detecting that the user has been inactive for a prolonged period, and provide relevant assistance and information.

### Core Features

- 🤖 **Intelligent Detection**: Monitors session activity status and triggers when inactivity is detected for a set period
- 🧠 **Context Analysis**: Analyzes user's conversation history and current screen content to identify potential needs
- 🔍 **Goal Extraction**: Extracts topics that the user may be focusing on from conversation history
- 💬 **Proactive Response**: Generates helpful and relevant proactive messages based on analysis results

### Important Notice

**Please be aware of the following risks before enabling this mode:**

- **Tool Protection Bypass**: In this mode, the Agent **bypasses standard tool protection mechanisms**. This means the Agent has higher system privileges and execution freedom.
- **Privacy and Environment Access**: The Agent **reads historical session memory** to understand context and **may take screenshots** to obtain current runtime environment information. Please ensure use in a trusted environment and protect sensitive information.
- This mode is **disabled by default**. It only takes effect when actively enabled by the user and can be disabled after being turned on.

### Basic Usage

#### Enable Proactive Mode

```bash
/proactive
/proactive on
/proactive <minutes>
```

**Example:**

```bash
/proactive      # Default 30 minutes, trigger proactive notification after 30 minutes of inactivity
/proactive on   # Same as above, default 30 minutes
/proactive 60   # Trigger proactive notification after 60 minutes
```

#### Disable Proactive Mode

```bash
/proactive off
```

### How It Works

1. **Monitoring Phase**: Continuously monitors user activity, recording the last activity timestamp
2. **Analysis Phase**: When inactivity exceeding the set time is detected, analyzes recent conversation history
3. **Task Extraction**: Identifies topics the user may be concerned about
4. **Query Execution**: Uses tools like browser, file reading, command execution to obtain relevant information
5. **Response Generation**: Generates friendly and relevant proactive assistance information

#### Context Awareness

- Focuses only on user-initiated messages, ignoring system messages
- Avoids repeatedly sending proactive messages on the same topics
- Prioritizes frequent and recently mentioned topics

### Important Notes

1. **Resource Consumption**: Enables regular context analysis after activation, which may increase computational resource usage
2. **Distraction Control**: If the user does not respond to proactive messages, no consecutive proactive messages will be sent
3. **Model Dependency**: Function effectiveness depends on the AI model capability used; multimodal-enabled models can better utilize screen analysis features

### Typical Use Cases

- New information acquisition during research processes
- Supplementary knowledge provision during learning processes

---
