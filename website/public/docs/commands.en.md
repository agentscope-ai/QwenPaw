# Magic Commands

**Magic commands** are special instructions prefixed with `/` that let you directly control conversation state without waiting for the AI to interpret your intent.

| Command        | Wait   | Compressed Summary | Long-term Memory   | Response Content              |
| -------------- | ------ | ------------------ | ------------------ | ----------------------------- |
| `/history`     | ⚡ No  | -                  | -                  | 📋 Message list + Token stats |
| `/message`     | ⚡ No  | -                  | -                  | 📄 Specified message details  |
| `/compact_str` | ⚡ No  | -                  | -                  | 📝 Compressed summary content |
| `/compact`     | ⏳ Yes | 📦 Generate new    | ✅ Background save | ✅ Compact complete + Summary |
| `/new`         | ⚡ No  | 🗑️ Clear           | ✅ Background save | ✅ New conversation prompt    |
| `/clear`       | ⚡ No  | 🗑️ Clear           | ❌ No save         | ✅ History cleared prompt     |

---

## /history — View Current Conversation History

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
```

> 💡 **Tip**: Use `/history` frequently to monitor your context usage.
>
> When `Context usage` approaches 75%, the conversation is about to trigger auto-`compact`.
>
> If context exceeds the maximum limit, please report the model and `/history` logs to the community, then use `/compact` or `/new` to manage context.
>
> Token calculation logic: [ReMeInMemoryMemory implementation](https://github.com/agentscope-ai/ReMe/blob/v0.3.0.6b2/reme/memory/file_based/reme_in_memory_memory.py#L122).

---

## /message — View Single Message

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

## /compact_str — View Compressed Summary

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

## /compact — Compress Current Conversation

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

> Unlike auto-compaction, `/compact` compresses **all** current messages, not just the portion exceeding the threshold.

---

## /new — Clear Context and Save Memories

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

## /clear — Clear Context (Without Saving Memories)

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

## Daemon Commands (Ops)

In chat, send `/daemon <subcommand>` or use short names (e.g., `/status` is equivalent to `/daemon status`). From the terminal, run `copaw daemon <subcommand>`. These run without going through the Agent.

| Command                             | Description                                                                                    |
| ----------------------------------- | ---------------------------------------------------------------------------------------------- |
| `/daemon status` or `/status`       | Show runtime status (config, working directory, memory service, etc.)                          |
| `/daemon restart` or `/restart`     | In-process restart (channels, cron, MCP) when in chat; from CLI prints instructions only       |
| `/daemon reload-config`             | Re-read and validate config (channel/MCP changes require `/daemon restart` or process restart) |
| `/daemon version`                   | Version number, working directory, log path                                                    |
| `/daemon logs` or `/daemon logs 50` | View last N lines of console log (default 100, from `copaw.log` in working directory)          |

From the terminal:

```bash
copaw daemon status
copaw daemon version
copaw daemon logs -n 50
```
