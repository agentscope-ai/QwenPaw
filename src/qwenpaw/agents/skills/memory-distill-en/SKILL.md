---
name: memory-distill
description: Smart memory distillation tool. Uses title-diffing to detect genuinely new information from daily notes (~92% noise reduction) and incrementally appends to MEMORY.md. Ideal for periodic memory consolidation.
metadata:
  builtin_skill_version: "1.0"
  qwenpaw:
    emoji: "🧠"
---

# Memory Distillation

## When to Use

Use this skill when you need to **consolidate and compress memory**:

### Should Use
- Agent detects duplicate information between MEMORY.md and daily notes
- User asks "consolidate my memory" or "distill notes"
- Periodic maintenance (every 7-15 days)
- Quick memory health check

### Should Not Use
- Just searching existing memory → use `memory_search`
- Just logging a single piece of information → directly update MEMORY.md or daily note
- No memory management needed

## Available Tools

Three tool functions (registered via the `memory-distill` plugin):

| Function | Purpose | Common Args |
|:---|:---|---:|
| `distill_memory()` | Title-diffing — scan daily notes, find new info | `days=7`, `dry_run=True` |
| `consolidate_memory()` | Full pipeline — distill → archive → clean → audit | `days=15`, `dry_run=True` |
| `inspect_memory()` | Quick health check | none |

## Workflow

### 1. Check health first
```python
result = await inspect_memory()
```

### 2. Preview distillation (always dry-run first)
```python
result = await distill_memory(days=7, dry_run=True)
```

### 3. Apply distillation
```python
result = await distill_memory(days=7, dry_run=False)
```

### 4. Full consolidation
```python
# Run every 15 days
result = await consolidate_memory(days=15, dry_run=False)
```

## Core Algorithm

1. **Title-diffing**: Extracts `**bold keywords**` and `###` headers from MEMORY.md as "known topics", compares against daily notes' `##` section titles
2. **Template filtering**: Auto-skips 15+ common template titles (e.g. "Goal", "Progress", "Key Decisions")
3. **Incremental append**: New discoveries are appended to an independent `🔄 Auto Discovery` section without rewriting MEMORY.md
4. **~92% noise reduction**: Far less redundant than pure LLM-driven approaches

## Notes

- Always start with `dry_run=True` to preview before applying
- Original daily notes are never deleted (only selectively appended to MEMORY.md)
- `consolidate_memory` archives old log files to `archive/` directory
