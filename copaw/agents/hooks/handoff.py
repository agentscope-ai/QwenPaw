# -*- coding: utf-8 -*-
"""Handoff hook for session continuity.

Generates a structured handoff manifest when sessions are compressed,
reach turn limits, or at regular intervals. New sessions load the
latest manifest to quickly resume context.
"""
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from agentscope.agent import ReActAgent
from agentscope.message import Msg, TextBlock

from ...config.config import load_agent_config
from ...config.context import get_current_workspace_dir

if TYPE_CHECKING:
    from ..memory import MemoryManager

logger = logging.getLogger(__name__)

HANDOFF_DIR = "handoff"
LATEST_FILE = "latest.md"

# Prompt for LLM to generate handoff manifest
HANDOFF_PROMPT = """Based on the conversation below, generate a concise handoff manifest in the following markdown format.
Be specific and actionable. Only include sections that have content.

```markdown
# 交付清单
生成时间：{timestamp}
触发原因：{trigger}

## 目标
(What is the user trying to accomplish?)

## 已完成
- [x] (Completed items with brief descriptions)

## 进行中
- [ ] (Items currently in progress)

## 关键决策
- (Important decisions made during this session)

## 关键上下文
- (Environment info, paths, configs, constraints that matter)

## 下次继续
(What should the next session start with?)
```

Conversation:
{conversation}"""


class HandoffHook:
    """Generates and loads handoff manifests for session continuity."""

    def __init__(self, memory_manager: "MemoryManager"):
        self.memory_manager = memory_manager

    def _get_handoff_dir(self) -> Path:
        """Get the handoff directory for current workspace."""
        workspace = get_current_workspace_dir()
        if workspace is None:
            workspace = Path(".")
        handoff_dir = workspace / HANDOFF_DIR
        handoff_dir.mkdir(parents=True, exist_ok=True)
        return handoff_dir

    async def generate(
        self,
        agent: ReActAgent,
        messages: list,
        trigger: str = "manual",
    ) -> Optional[str]:
        """Generate a handoff manifest from current conversation.

        Args:
            agent: The agent instance
            messages: Current message list
            trigger: What triggered the handoff

        Returns:
            Path to the generated manifest, or None on failure
        """
        try:
            # Build conversation text from recent messages (last 30)
            recent = messages[-30:] if len(messages) > 30 else messages
            conversation_parts = []
            for msg in recent:
                role = getattr(msg, "role", "unknown")
                content = ""
                if hasattr(msg, "get_text_content"):
                    content = msg.get_text_content() or ""
                elif hasattr(msg, "content"):
                    c = msg.content
                    if isinstance(c, str):
                        content = c
                    elif isinstance(c, list):
                        content = " ".join(
                            b.text for b in c
                            if hasattr(b, "text") and b.text
                        )
                if content:
                    conversation_parts.append(f"[{role}]: {content[:500]}")

            if not conversation_parts:
                logger.debug("No conversation content for handoff")
                return None

            conversation_text = "\n".join(conversation_parts)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

            prompt = HANDOFF_PROMPT.format(
                timestamp=timestamp,
                trigger=trigger,
                conversation=conversation_text,
            )

            # Use memory_manager's summarize capability
            manifest_content = await self.memory_manager.summarize_text(
                prompt
            )

            if not manifest_content:
                # Fallback: generate a minimal manifest without LLM
                manifest_content = self._build_minimal_manifest(
                    timestamp, trigger, conversation_parts
                )

            # Save to files
            handoff_dir = self._get_handoff_dir()

            # Save as latest
            latest_path = handoff_dir / LATEST_FILE
            latest_path.write_text(manifest_content, encoding="utf-8")

            # Save timestamped copy
            ts_filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{trigger}.md"
            ts_path = handoff_dir / ts_filename
            ts_path.write_text(manifest_content, encoding="utf-8")

            logger.info(
                "Handoff manifest generated: %s (trigger=%s)",
                latest_path, trigger,
            )
            return str(latest_path)

        except Exception as e:
            logger.warning("Failed to generate handoff manifest: %s", e)
            return None

    def _build_minimal_manifest(
        self,
        timestamp: str,
        trigger: str,
        conversation_parts: list[str],
    ) -> str:
        """Build a minimal manifest without LLM when summarization fails."""
        last_messages = conversation_parts[-5:]
        recent_text = "\n".join(f"  {m}" for m in last_messages)
        return (
            f"# 交付清单\n"
            f"生成时间：{timestamp}\n"
            f"触发原因：{trigger}\n\n"
            f"## 最近对话\n{recent_text}\n"
        )

    @staticmethod
    def load_latest(workspace_dir: Optional[Path] = None) -> Optional[str]:
        """Load the latest handoff manifest.

        Args:
            workspace_dir: Workspace directory. Uses context var if None.

        Returns:
            Manifest content string, or None if not found.
        """
        if workspace_dir is None:
            workspace_dir = get_current_workspace_dir()
        if workspace_dir is None:
            return None

        latest_path = workspace_dir / HANDOFF_DIR / LATEST_FILE
        if not latest_path.exists():
            return None

        try:
            content = latest_path.read_text(encoding="utf-8").strip()
            if content:
                logger.info("Loaded handoff manifest from %s", latest_path)
                return content
        except Exception as e:
            logger.warning("Failed to load handoff manifest: %s", e)

        return None
