# -*- coding: utf-8 -*-
"""Memory compaction hook for managing context window.

This hook monitors token usage and automatically compacts older messages
when the context window approaches its limit, preserving recent messages
and the system prompt.
"""
import logging
from typing import TYPE_CHECKING, Any

from agentscope.agent import ReActAgent
from agentscope.message import Msg, TextBlock
from copaw.constant import MEMORY_COMPACT_KEEP_RECENT

from ..utils import (
    check_valid_messages,
    get_copaw_token_counter,
)
from ...config.config import load_agent_config

if TYPE_CHECKING:
    from ..memory import MemoryManager
    from reme.memory.file_based import ReMeInMemoryMemory

logger = logging.getLogger(__name__)


class MemoryCompactionHook:
    """Hook for automatic memory compaction when context is full.

    This hook monitors the token count of messages and triggers compaction
    when it exceeds the threshold. It preserves the system prompt and recent
    messages while summarizing older conversation history.
    """

    def __init__(self, memory_manager: "MemoryManager"):
        """Initialize memory compaction hook.

        Args:
            memory_manager: Memory manager instance for compaction
        """
        self.memory_manager = memory_manager

    @staticmethod
    async def _print_status_message(
        agent: ReActAgent,
        text: str,
    ) -> None:
        """Print a status message to the agent's output.

        Args:
            agent: The agent instance to print the message for.
            text: The text content of the status message.
        """
        msg = Msg(
            name=agent.name,
            role="assistant",
            content=[TextBlock(type="text", text=text)],
        )
        await agent.print(msg)

    async def __call__(
        self,
        agent: ReActAgent,
        kwargs: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Pre-reasoning hook to check and compact memory if needed.

        This hook extracts system prompt messages and recent messages,
        builds an estimated full context prompt, and triggers compaction
        when the total estimated token count exceeds the threshold.

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
            # Get hot-reloaded agent config
            agent_config = load_agent_config(self.memory_manager.agent_id)
            running_config = agent_config.running
            token_counter = get_copaw_token_counter(agent_config)

            memory: "ReMeInMemoryMemory" = agent.memory

            system_prompt = agent.sys_prompt
            compressed_summary = memory.get_compressed_summary()
            str_token_count = await token_counter.count(
                messages=[],
                text=(system_prompt or "") + (compressed_summary or ""),
            )

            # memory_compact_threshold is always available from config
            left_compact_threshold = (
                running_config.memory_compact_threshold - str_token_count
            )

            if left_compact_threshold <= 0:
                logger.warning(
                    "The memory_compact_threshold is set too low; "
                    "the combined token length of system_prompt and "
                    "compressed_summary exceeds the configured threshold. "
                    "Alternatively, you could use /clear to reset the context "
                    "and compressed_summary, ensuring the total remains "
                    "below the threshold.",
                )
                return None

            messages = await memory.get_memory(prepend_summary=False)

            # Compact tool results with configured thresholds
            recent_threshold = (
                running_config.tool_result_compact_recent_threshold
            )
            retention_days = running_config.tool_result_compact_retention_days
            await self.memory_manager.compact_tool_result(
                messages=messages,
                recent_n=running_config.tool_result_compact_recent_n,
                old_threshold=running_config.tool_result_compact_old_threshold,
                recent_threshold=recent_threshold,
                retention_days=retention_days,
            )

            # memory_compact_reserve is always available from config
            (
                messages_to_compact,
                _,
                is_valid,
            ) = await self.memory_manager.check_context(
                messages=messages,
                memory_compact_threshold=left_compact_threshold,
                memory_compact_reserve=running_config.memory_compact_reserve,
                as_token_counter=token_counter,
            )

            if not messages_to_compact:
                return None

            if not is_valid:
                logger.warning(
                    "Please include the output of the /history command when "
                    "reporting the bug to the community. Invalid "
                    "messages=%s",
                    messages,
                )
                keep_length: int = MEMORY_COMPACT_KEEP_RECENT
                messages_length = len(messages)
                while keep_length > 0 and not check_valid_messages(
                    messages[max(messages_length - keep_length, 0) :],
                ):
                    keep_length -= 1

                if keep_length > 0:
                    messages_to_compact = messages[
                        : max(messages_length - keep_length, 0)
                    ]
                else:
                    messages_to_compact = messages

            if not messages_to_compact:
                return None

            self.memory_manager.add_async_summary_task(
                messages=messages_to_compact,
            )
            await self._print_status_message(
                agent,
                "🔄 Context compaction started...",
            )

            compact_content = await self.memory_manager.compact_memory(
                messages=messages_to_compact,
                previous_summary=memory.get_compressed_summary(),
            )

            if not compact_content:
                logger.error("Memory compaction returned empty result")
                await self._print_status_message(
                    agent,
                    "⚠️ Context compaction failed. "
                    "If context exceeds max length, "
                    "please use /new or /clear to clear the context.",
                )
            else:
                await self._print_status_message(
                    agent,
                    "✅ Context compaction completed",
                )

                updated_count = await memory.mark_messages_compressed(
                    messages_to_compact,
                )
                logger.info(f"Marked {updated_count} messages as compacted")

            await agent.memory.update_compressed_summary(compact_content)

        except Exception as e:
            logger.exception(
                "Failed to compact memory in pre_reasoning hook: %s",
                e,
                exc_info=True,
            )

        return None
