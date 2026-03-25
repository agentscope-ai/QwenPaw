# -*- coding: utf-8 -*-
"""E3: Cross-task knowledge distillation.

When a task is completed, distill key learnings from the task's result_summary
and context into the agent's MEMORY.md and daily note.

Usage:
    from copaw.agents.memory.distiller import distill_task
    distill_task(task=completed_task, agent_id='agent-a', workspace_dir=Path(...))
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def distill_task(
    task,  # TeamTask instance
    agent_id: str,
    workspace_dir: Path,
) -> bool:
    """E3: Distill completed task knowledge into agent memory files.

    Reads task.result_summary and task.context_dir, generates a brief
    distillation entry, and appends it to:
      - workspace_dir/memory/YYYY-MM-DD.md  (daily note)
      - workspace_dir/MEMORY.md             (long-term memory)

    Returns True if distillation was written, False if skipped.
    """
    if not task.result_summary and not task.context_dir:
        logger.debug("E3: task %s has no result_summary or context_dir, skipping", task.id)
        return False

    entry = _build_entry(task, agent_id)
    if not entry:
        return False

    today = datetime.now().strftime("%Y-%m-%d")
    _append_to_daily_note(workspace_dir, today, entry)
    _append_to_memory(workspace_dir, entry, task.title)
    logger.info("E3: distilled task %s (%s) to agent %s memory", task.id, task.title, agent_id)
    return True


def _build_entry(task, agent_id: str) -> str:
    """Build a distillation entry string from task info."""
    parts = []
    parts.append(f"### 任务完成：{task.title} (id={task.id})")
    parts.append(f"- **完成人：** {agent_id}")
    if task.completed_at:
        ts = datetime.fromtimestamp(task.completed_at).strftime("%Y-%m-%d %H:%M")
        parts.append(f"- **完成时间：** {ts}")
    if task.result_summary:
        parts.append(f"- **结果摘要：** {task.result_summary}")
    # Try to read key files from context_dir
    if task.context_dir:
        ctx = Path(task.context_dir)
        if ctx.exists():
            notes = []
            for f in sorted(ctx.iterdir()):
                if f.suffix in (".md", ".txt") and f.stat().st_size < 4096:
                    try:
                        content = f.read_text(encoding="utf-8").strip()[:300]
                        notes.append(f"  - {f.name}: {content}")
                    except Exception:
                        pass
            if notes:
                parts.append("- **上下文笔记：**")
                parts.extend(notes)
    if task.history:
        parts.append(f"- **状态变更次数：** {len(task.history)}")
    return "\n".join(parts)


def _append_to_daily_note(workspace_dir: Path, today: str, entry: str) -> None:
    """Append entry to memory/YYYY-MM-DD.md."""
    memory_dir = workspace_dir / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    daily_file = memory_dir / f"{today}.md"
    separator = "\n\n---\n\n" if daily_file.exists() else ""
    with daily_file.open("a", encoding="utf-8") as f:
        f.write(f"{separator}## E3 任务知识提炼 — {today}\n\n{entry}\n")


def _append_to_memory(workspace_dir: Path, entry: str, task_title: str) -> None:
    """Append condensed entry to MEMORY.md under a dedicated section."""
    memory_file = workspace_dir / "MEMORY.md"
    section_header = "## 任务经验积累"
    condensed = f"- **{task_title}**：" + (entry.split("结果摘要：")[-1].split("\n")[0].strip() if "结果摘要：" in entry else "已完成")
    if memory_file.exists():
        content = memory_file.read_text(encoding="utf-8")
        if section_header in content:
            # Append under existing section
            updated = content.replace(
                section_header,
                section_header + "\n" + condensed,
                1,
            )
            memory_file.write_text(updated, encoding="utf-8")
            return
    # Append section at end
    with memory_file.open("a", encoding="utf-8") as f:
        f.write(f"\n\n{section_header}\n{condensed}\n")
