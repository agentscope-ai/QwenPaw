# -*- coding: utf-8 -*-
"""Memory compaction hook for managing context window.

This hook monitors token usage and automatically compacts older messages
when the context window approaches its limit, preserving recent messages
and the system prompt.
"""
import logging
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from agentscope.agent._react_agent import _MemoryMark, ReActAgent

from copaw.config import load_config
from copaw.constant import MEMORY_COMPACT_KEEP_RECENT
from ..utils import (
    check_valid_messages,
    safe_count_str_tokens,
)

if TYPE_CHECKING:
    from ..memory import MemoryManager
    from reme.memory.file_based import ReMeInMemoryMemory

logger = logging.getLogger(__name__)


def _normalize_check_context_result(
    result: Any,
) -> tuple[list[Any], bool]:
    """Normalize check_context results across dependency versions.

    CoPaw only needs two fields from ``check_context``:
    ``messages_to_compact`` and ``is_valid``. Upstream implementations may
    evolve from a plain 3-tuple to a richer tuple, mapping, or typed object.
    This adapter keeps the hook stable as long as those two semantics remain
    available.
    """
    if isinstance(result, Mapping):
        try:
            return result["messages_to_compact"], bool(result["is_valid"])
        except KeyError as exc:
            raise ValueError(
                "check_context result mapping is missing required keys: "
                "'messages_to_compact' and/or 'is_valid'",
            ) from exc

    if hasattr(result, "messages_to_compact") and hasattr(result, "is_valid"):
        return result.messages_to_compact, bool(result.is_valid)

    if isinstance(result, Sequence) and not isinstance(result, (str, bytes)):
        if len(result) < 3:
            raise ValueError(
                "check_context result must contain at least 3 items, "
                f"got {len(result)}",
            )
        return result[0], bool(result[2])

    raise TypeError(
        "Unsupported check_context result type: " f"{type(result).__name__}",
    )


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
            memory: "ReMeInMemoryMemory" = agent.memory
            token_counter = self.memory_manager.token_counter

            system_prompt = agent.sys_prompt
            compressed_summary = memory.get_compressed_summary()
            str_token_count = safe_count_str_tokens(
                system_prompt + compressed_summary,
            )

            config = load_config()
            memory_compact_threshold = (
                config.agents.running.memory_compact_threshold
            )
            left_compact_threshold = memory_compact_threshold - str_token_count

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

            enable_tool_result_compact = (
                config.agents.running.enable_tool_result_compact
            )
            tool_result_compact_keep_n = (
                config.agents.running.tool_result_compact_keep_n
            )
            if enable_tool_result_compact and tool_result_compact_keep_n > 0:
                compact_msgs = messages[:-tool_result_compact_keep_n]
                await self.memory_manager.compact_tool_result(compact_msgs)

            memory_compact_reserve = (
                config.agents.running.memory_compact_reserve
            )
            check_context_result = await self.memory_manager.check_context(
                messages=messages,
                memory_compact_threshold=left_compact_threshold,
                memory_compact_reserve=memory_compact_reserve,
                token_counter=token_counter,
            )
            messages_to_compact, is_valid = _normalize_check_context_result(
                check_context_result,
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

            compact_content = await self.memory_manager.compact_memory(
                messages=messages_to_compact,
                previous_summary=memory.get_compressed_summary(),
            )

            await agent.memory.update_compressed_summary(compact_content)
            updated_count = await memory.update_messages_mark(
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
