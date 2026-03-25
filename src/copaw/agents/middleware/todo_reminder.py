# -*- coding: utf-8 -*-
"""Todo reminder middleware.

After memory compaction, the agent's todo/task list context may be lost.
This middleware detects that situation and re-injects a reminder from
the handoff manifest or MEMORY.md so the agent stays on track.

Runs as a pre_reasoning hook.
"""
import logging
from pathlib import Path
from typing import Any

from agentscope.agent import ReActAgent
from agentscope.message import Msg, TextBlock

from ...config.context import get_current_workspace_dir

logger = logging.getLogger(__name__)


class TodoReminderMiddleware:
    """Detect lost todo context after compaction and re-inject reminders."""

    def __init__(self):
        self._last_known_summary_hash: str | None = None
        self._reminder_injected = False

    def _summary_changed(self, memory) -> bool:
        """Check if compressed_summary changed (indicates compaction happened)."""
        summary = ""
        if hasattr(memory, "get_compressed_summary"):
            summary = memory.get_compressed_summary() or ""

        current_hash = str(hash(summary))
        if self._last_known_summary_hash is None:
            self._last_known_summary_hash = current_hash
            return False

        if current_hash != self._last_known_summary_hash:
            self._last_known_summary_hash = current_hash
            self._reminder_injected = False  # Reset on new compaction
            return True
        return False

    def _has_todo_in_recent_messages(self, memory, lookback: int = 10) -> bool:
        """Check if recent messages contain todo/task references."""
        if not hasattr(memory, "content") or not memory.content:
            return False

        recent = memory.content[-lookback:]
        todo_keywords = [
            "进行中", "待完成", "下一步", "TODO", "todo",
            "- [ ]", "- [x]", "任务", "交付清单",
        ]

        for item in recent:
            msg = item[0] if isinstance(item, tuple) else item
            content = ""
            if hasattr(msg, "get_text_content"):
                content = msg.get_text_content() or ""
            elif hasattr(msg, "content"):
                c = msg.content
                if isinstance(c, str):
                    content = c
                elif isinstance(c, list):
                    content = " ".join(
                        getattr(b, "text", "") for b in c
                    )

            for kw in todo_keywords:
                if kw in content:
                    return True
        return False

    def _load_todo_reminder(self) -> str | None:
        """Load todo context from handoff manifest."""
        workspace = get_current_workspace_dir()
        if workspace is None:
            return None

        # Try handoff/latest.md first
        handoff_path = workspace / "handoff" / "latest.md"
        if handoff_path.exists():
            try:
                content = handoff_path.read_text(encoding="utf-8")
                # Extract "进行中" and "下次继续" sections
                sections = []
                in_section = False
                for line in content.split("\n"):
                    if any(h in line for h in [
                        "## 进行中", "## 下次继续", "## 目标",
                    ]):
                        in_section = True
                        sections.append(line)
                    elif line.startswith("## ") and in_section:
                        in_section = False
                    elif in_section:
                        sections.append(line)

                if sections:
                    return "\n".join(sections).strip()
            except Exception:
                pass

        return None

    async def __call__(
        self,
        agent: ReActAgent,
        kwargs: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Pre-reasoning hook: check for lost todo context after compaction."""
        try:
            if not self._summary_changed(agent.memory):
                return None

            # Compaction just happened — check if todos are still visible
            if self._has_todo_in_recent_messages(agent.memory):
                return None

            if self._reminder_injected:
                return None

            # Load and inject reminder
            reminder = self._load_todo_reminder()
            if not reminder:
                return None

            self._reminder_injected = True
            logger.info("Injecting todo reminder after compaction")

            reminder_msg = Msg(
                name="system",
                role="system",
                content=[TextBlock(
                    type="text",
                    text=(
                        "📋 上下文压缩后提醒 — 以下是当前进行中的任务：\n\n"
                        f"{reminder}"
                    ),
                )],
            )
            agent.memory.add(reminder_msg)

        except Exception as e:
            logger.debug("TodoReminder error (non-fatal): %s", e)

        return None
