# Memory Distillation Tool Plugin 🧠

Advanced memory consolidation for QwenPaw agents. Detects genuinely new information in daily notes using **title-diffing** — comparing MEMORY.md's known topics against daily notes' section titles — achieving ~92% noise reduction.

## Features

| Tool | Description |
|:---|:---|
| `distill_memory()` | Title-diffing engine — scan daily notes, find genuinely new info, optionally append to MEMORY.md |
| `consolidate_memory()` | Full pipeline: distill → archive → clean → audit |
| `inspect_memory()` | Quick health check for MEMORY.md and daily notes |

### How Title-Diffing Works

1. **Extract known topics**: Parses `**bold markers**` and `###` headers from MEMORY.md as "known topics"
2. **Scan daily notes**: Reads `memory/YYYY-MM-DD.md` files, extracts `## Title` sections
3. **Template filtering**: Auto-skips 15+ common template titles (e.g. "计划", "goal", "key decisions")
4. **Discovery**: Only new, non-template, meaningful titles pass through
5. **Incremental append**: New discoveries go into `🔄 Auto Discovery` section without rewriting MEMORY.md

### Three-Tier Classification

| Tier | Rule | Emoji | Output |
|:---|:---|:---:|:---|
| 🔒 **Ironclad** | Keywords: *config, setup, project, architecture* | 🔒 | Full entry in MEMORY.md |
| 📌 **Important** | Keywords: *decision, change, preference, lesson* | 📌 | Brief pointer in MEMORY.md |
| ➕ **Minor** | Everything else | ➕ | Kept in daily notes only |

## Installation

```bash
qwenpaw plugin install /path/to/memory-distill
```

Or from ZIP:

```bash
qwenpaw plugin install memory-distill-tool.zip
```

## Configuration

This plugin works **out of the box** — no API keys or external services required.

1. Start QwenPaw application
2. Navigate to Agent Settings → Tools
3. Find the `consolidate_memory` tool (🧠 icon)
4. Enable the tool
5. (Optional) Configure working directory if not using default

**Requirements:**
- `MEMORY.md` in the agent's working directory
- `memory/YYYY-MM-DD.md` daily notes files

## Usage

Once configured and enabled, the Agent can call these tools:

**User**: Review what I've been working on and consolidate my memory

**Agent**: [Calls consolidate_memory tool to run the full pipeline]

### Tool Parameters

#### distill_memory

Scan daily notes and discover genuinely new information.

**Parameters:**

- `days` (int, optional): Number of days to look back (default: 7)
- `dry_run` (bool, optional): Preview only — don't modify MEMORY.md (default: True)
- `working_dir` (str, optional): Override working directory

**Returns:**

- TextBlock with discovered items per daily note
- Summary statistics (total scanned, new found, skipped templates)

#### consolidate_memory

Full consolidation pipeline: distill → archive daily notes → clean temp files → audit.

**Parameters:**

- `days` (int, optional): Number of days to look back (default: 15)
- `dry_run` (bool, optional): Preview only — don't modify files (default: True)
- `working_dir` (str, optional): Override working directory

**Returns:**

- Detailed report of each pipeline step
- Distillation results
- Archive summary (files moved to `archive/`)
- Cleanup stats

#### inspect_memory

Quick health check for memory files.

**Parameters:**

- `working_dir` (str, optional): Override working directory

**Returns:**

- MEMORY.md file size and line count
- Daily notes file count and date range
- Known topics count
- Any issues found

## Requirements

- QwenPaw >= 1.1.6
- Works with any agent workspace containing `MEMORY.md` and `memory/` daily notes

## Comparison with `dream()` Memory Optimization

| Aspect | `dream()` (Built-in) | `memory-distill` (Plugin) |
|:---|:---|:---|
| **Approach** | LLM-based ReAct agent reads & rewrites MEMORY.md intelligently | Algorithmic title-diffing — pattern matching, no LLM calls |
| **Trigger** | Background, periodic (part of light memory lifecycle) | On-demand via tool calls |
| **Output** | Full rewrite of MEMORY.md with LLM-optimized content | Incremental append to `🔄 Auto Discovery` section — never touches existing content |
| **Cost** | LLM API cost per run | Zero API cost (pure algorithmic) |
| **Noise Reduction** | LLM-dependent, can hallucinate or lose info | Deterministic ~92% reduction via template+known-topic filtering |
| **Deduplication** | LLM merges related entries intelligently | Title-level dedup only (same title = skip) |
| **Best for** | Deep, holistic memory cleanup; removing outdated entries | Quick, safe, daily discovery of genuinely new information |

**When to use each:**
- Use **memory-distill** daily/regularly — it's cheap, safe, and catches new info
- Use **dream()** periodically (e.g., weekly) — for intelligent cleanup, merging, and removing stale entries
- They are **complementary**: memory-distill feeds new discoveries, dream() maintains overall quality

## Troubleshooting

### Tool not showing up

- Ensure the plugin is installed: `qwenpaw plugin list`
- Check QwenPaw logs: `~/.qwenpaw/logs/qwenpaw.log`
- Restart QwenPaw after installation

### No discoveries found

- Ensure daily notes exist in `memory/YYYY-MM-DD.md` format
- Check that section titles in daily notes use `##` headers
- Verify MEMORY.md has `**bold topics**` for known-topic extraction
- Template titles (e.g., "计划", "goal") are auto-filtered

### Consolidation not taking effect

- Run with `dry_run=False` (default is True for safety)
- Check working directory path
- Review logs for error messages

## Development

To modify this plugin:

1. Edit `tool.py` for tool logic (distill, consolidate, inspect)
2. Edit `plugin.py` for registration logic
3. Edit `plugin.json` for metadata
4. Reinstall with `--force` flag

## License

Same as QwenPaw

## Support

For issues and feature requests, please use the QwenPaw issue tracker.
