# -*- coding: utf-8 -*-
"""Memory compaction hook for managing context window.

This hook monitors token usage and automatically compacts older messages
when the context window approaches its limit, preserving recent messages
and the system prompt.
"""
import logging
import os
from typing import TYPE_CHECKING, Any

from agentscope.agent._react_agent import _MemoryMark

from ..utils import (
    check_valid_messages,
    safe_count_message_tokens,
)
from ..utils.tool_message_utils import _truncate_text

if TYPE_CHECKING:
    from ..memory import MemoryManager

logger = logging.getLogger(__name__)

# Default max length for tool result text truncation during compaction
_DEFAULT_COMPACT_TOOL_RESULT_MAX_LENGTH = 10000


def _truncate_tool_result_texts(
    messages: list,
    max_length: int | None = None,
) -> None:
    """Truncate text content in tool_result blocks within messages.

    Args:
        messages: List of Msg objects to process
        max_length: Maximum allowed length for text content
                   (from env TOOL_RESULT_MAX_LENGTH or default 10000)
    """
    if max_length is None:
        max_length = int(
            os.environ.get(
                "DEFAULT_COMPACT_TOOL_RESULT_MAX_LENGTH",
                _DEFAULT_COMPACT_TOOL_RESULT_MAX_LENGTH,
            ),
        )

    for msg in messages:
        # Use get_content_blocks to properly extract tool_result blocks
        tool_result_blocks = msg.get_content_blocks("tool_result")

        for block in tool_result_blocks:
            output = block.get("output")
            if isinstance(output, str):
                # Direct string output
                block["output"] = _truncate_text(output, max_length)
            elif isinstance(output, list):
                # List of content blocks (TextBlock, ImageBlock, etc.)
                for item in output:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text = item.get("text", "")
                        item["text"] = _truncate_text(text, max_length)


class MemoryCompactionHook:
    """Hook for automatic memory compaction when context is full.

    This hook monitors the token count of messages and triggers compaction
    when it exceeds the threshold. It preserves the system prompt and recent
    messages while summarizing older conversation history.
    """

    def __init__(
        self,
        memory_manager: "MemoryManager",
        memory_compact_threshold: int,
        keep_recent: int = 10,
    ):
        """Initialize memory compaction hook.

        Args:
            memory_manager: Memory manager instance for compaction
            memory_compact_threshold: Token count threshold for compaction
            keep_recent: Number of recent messages to preserve
        """
        self.memory_manager = memory_manager
        self.memory_compact_threshold = memory_compact_threshold
        self.keep_recent = keep_recent

    @property
    def enable_truncate_tool_result_texts(self) -> bool:
        """Whether to truncate tool result texts.

        Controlled by environment variable ENABLE_TRUNCATE_TOOL_RESULT_TEXTS.
        Default is False (disabled).
        """
        return os.environ.get(
            "ENABLE_TRUNCATE_TOOL_RESULT_TEXTS",
            "false",
        ).lower() in ("true", "1", "yes")

    async def __call__(
        self,
        agent,
        kwargs: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Pre-reasoning hook to check and compact memory if needed.

        This hook extracts system prompt messages and recent messages,
        then counts tokens for the middle compactable messages only.
        If the token count exceeds the threshold, it triggers compaction.

        Memory structure:
            [System Prompt (preserved)] + [Compactable (counted)] +
            [Recent (preserved)]

        Args:
            agent: The agent instance
            kwargs: Input arguments to the _reasoning method

        Returns:
            None (hook doesn't modify kwargs)
        """
        try:
            messages = await agent.memory.get_memory(
                exclude_mark=_MemoryMark.COMPRESSED,
                prepend_summary=False,
            )

            logger.debug(f"===last message===: {messages[-1]}")

            system_prompt_messages = []
            for msg in messages:
                if msg.role == "system":
                    system_prompt_messages.append(msg)
                else:
                    break

            remaining_messages = messages[len(system_prompt_messages) :]

            if len(remaining_messages) <= self.keep_recent:
                return None

            keep_length = self.keep_recent
            while keep_length > 0 and not check_valid_messages(
                remaining_messages[-keep_length:],
            ):
                keep_length -= 1

            if keep_length > 0:
                messages_to_compact = remaining_messages[:-keep_length]
                messages_to_keep = remaining_messages[-keep_length:]
            else:
                messages_to_compact = remaining_messages
                messages_to_keep = []

            # Truncate tool result texts in messages_to_keep
            if self.enable_truncate_tool_result_texts and messages_to_keep:
                _truncate_tool_result_texts(messages_to_keep)

            prompt = await agent.formatter.format(msgs=messages_to_compact)
            estimated_tokens: int = await safe_count_message_tokens(prompt)
            logger.debug(
                "Estimated tokens for compaction: %d vs %s",
                estimated_tokens,
                self.memory_compact_threshold,
            )

            if estimated_tokens > self.memory_compact_threshold:
                logger.info(
                    "Memory compaction triggered: estimated %d tokens "
                    "(threshold: %d), system_prompt_msgs: %d, "
                    "compactable_msgs: %d, keep_recent_msgs: %d",
                    estimated_tokens,
                    self.memory_compact_threshold,
                    len(system_prompt_messages),
                    len(messages_to_compact),
                    len(messages_to_keep),
                )

                self.memory_manager.add_async_summary_task(
                    messages=messages_to_compact,
                )

                compact_content = await self.memory_manager.compact_memory(
                    messages_to_summarize=messages_to_compact,
                    previous_summary=agent.memory.get_compressed_summary(),
                )

                await agent.memory.update_compressed_summary(compact_content)
                updated_count = await agent.memory.update_messages_mark(
                    new_mark=_MemoryMark.COMPRESSED,
                    msg_ids=[msg.id for msg in messages_to_compact],
                )
                logger.info(f"Marked {updated_count} messages as compacted")

        except Exception as e:
            logger.error(
                "Failed to compact memory in pre_reasoning hook: %s",
                e,
                exc_info=True,
            )

        return None
