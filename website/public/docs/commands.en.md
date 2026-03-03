# System Commands

> **Experimental**: System commands do not yet fully cover all scenarios and edge cases; using them may lead to errors or unexpected behavior. Please rely on actual behavior as the source of truth.

**System commands** are special instructions prefixed with `/` that let you directly control conversation state without waiting for the AI to interpret your intent.

Five commands are currently supported:

- **`/compact`** — Compress the current conversation, generate a summary and save memories
- **`/new`** — Start a new conversation, saving memories in the background
- **`/clear`** — Completely clear everything, without saving anything
- **`/history`** — View conversation history with detailed token usage breakdown
- **`/compact_str`** — View the current compressed summary (read-only)

> If you're not yet familiar with concepts like "compaction" or "long-term memory", we recommend reading the [Introduction](./intro.en.md) first.

---

## Command Comparison

| Command        | Requires Wait | Compressed Summary | Long-term Memory    | Message History     | Context Usage            |
| -------------- | ------------- | ------------------ | ------------------- | ------------------- | ------------------------ |
| `/compact`     | Yes           | Generates new      | Saved in background | Marked as compacted | -                        |
| `/new`         | No            | Cleared            | Saved in background | Marked as compacted | -                        |
| `/clear`       | No            | Cleared            | Not saved           | Fully cleared       | -                        |
| `/history`     | No            | -                  | -                   | Read-only view      | 📊 Token details + Usage |
| `/compact_str` | No            | -                  | -                   | -                   | 📖 View summary content  |

---

## /compact — Compress the Current Conversation

Manually trigger conversation compaction, condensing all current messages into a summary (requires waiting), while saving to long-term memory in the background.

```
/compact
```

Example response:

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

Immediately clear the current context and start a fresh conversation; history is saved to long-term memory in the background.

```
/new
```

Example response:

```
**New Conversation Started!**

- Summary task started in background
- Ready for new conversation
```

---

## /clear — Clear Context (Without Saving Memories)

Immediately clear the current context, including message history and compressed summaries. Nothing is saved to long-term memory.

```
/clear
```

Example response:

```
**History Cleared!**

- Compressed summary reset
- Memory is now empty
```

> ⚠️ `/clear` is **irreversible**! Unlike `/new`, cleared content will not be saved.

---

## /history — View Current Conversation History

Display a list of all uncompressed messages in the current conversation, along with detailed **context usage information**.

```
/history
```

Example response:

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

> 💡 **Tip**: Use `/history` frequently to monitor your context usage. When `Context usage` approaches 100%, it indicates the conversation is about to trigger auto-compaction. You can proactively use `/compact` or `/new` to manage context before this happens.

---

## /compact_str — View Compressed Summary

Display the current compressed summary content.

```
/compact_str
```

Example response (when summary exists):

```
**Compressed Summary**

User requested help building a user authentication system, login endpoint implementation completed...
```

Example response (when no summary):

```
**No Compressed Summary**

- No summary has been generated yet
- Use /compact or wait for auto-compaction
```

---

## Related Pages

- [Introduction](./intro.en.md) — What this project can do
- [Console](./console.en.md) — Manage Agent state in the console
- [Configuration & Working Directory](./config.en.md) — Working directory & config
- [CLI](./cli.en.md) — Command-line tool reference
