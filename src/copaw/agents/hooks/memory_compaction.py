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
    safe_count_str_tokens,
)

if TYPE_CHECKING:
    from ..memory import MemoryManager

logger = logging.getLogger(__name__)

# Maximum number of single-message drops in hard-limit enforcement to
# prevent infinite loops if token counting is unreliable.
_HARD_LIMIT_MAX_DROPS = 200


class MemoryCompactionHook:
    """Hook for automatic memory compaction when context is full.

    This hook monitors the token count of messages and triggers compaction
    when it exceeds the threshold. It preserves the system prompt and recent
    messages while summarizing older conversation history.

    Two levels of protection:
        1. **Soft threshold** (``memory_compact_threshold``): when exceeded,
           older messages are summarised via the memory-manager.  This is the
           normal compaction path.
        2. **Hard limit** (``hard_token_limit``): an absolute ceiling that
           must never be exceeded.  After compaction (or if compaction fails /
           is skipped), the hook re-estimates the token count and
           **forcibly drops** the oldest non-system messages one-by-one until
           the total falls below this limit.  This guarantees the next API
           call will not exceed the model's context window.
    """

    def __init__(
        self,
        memory_manager: "MemoryManager",
        memory_compact_threshold: int,
        keep_recent: int = 10,
        hard_token_limit: int = 0,
    ):
        """Initialize memory compaction hook.

        Args:
            memory_manager: Memory manager instance for compaction
            memory_compact_threshold: Token count threshold for compaction
            keep_recent: Number of recent messages to preserve
            hard_token_limit: Absolute token ceiling.  When > 0 the hook
                will forcibly discard the oldest messages after compaction
                so that the estimated token count stays below this value.
                Typically set to ``max_input_length`` (e.g. 131072).
        """
        self.memory_manager = memory_manager
        self.memory_compact_threshold = memory_compact_threshold
        self.keep_recent = keep_recent
        self.hard_token_limit = hard_token_limit

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
        builds an estimated full context prompt, and triggers compaction
        when the total estimated token count exceeds the threshold.

        After compaction (or if compaction is skipped), a hard-limit
        enforcement loop runs: if ``hard_token_limit`` is set and the
        estimated total still exceeds it, the oldest non-system messages
        are forcibly discarded (marked as COMPRESSED) one-by-one until
        the total falls below the limit.

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
                # Even when there are few messages, still enforce hard limit
                await self._enforce_hard_limit(agent)
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

            messages_for_estimate = [
                *system_prompt_messages,
                *messages_to_compact,
                *messages_to_keep,
            ]
            previous_summary = agent.memory.get_compressed_summary()
            full_prompt = await agent.formatter.format(
                msgs=messages_for_estimate,
            )
            estimated_message_tokens = await safe_count_message_tokens(
                full_prompt,
            )
            summary_tokens = safe_count_str_tokens(previous_summary)
            estimated_total_tokens = estimated_message_tokens + summary_tokens
            logger.debug(
                "Estimated context tokens total=%d "
                "(messages=%d, summary=%d, summary_prepended=%s, "
                "system_prompt_msgs=%d, "
                "compactable_msgs=%d, keep_recent_msgs=%d) vs threshold=%d",
                estimated_total_tokens,
                estimated_message_tokens,
                summary_tokens,
                bool(previous_summary),
                len(system_prompt_messages),
                len(messages_to_compact),
                len(messages_to_keep),
                self.memory_compact_threshold,
            )

            if estimated_total_tokens > self.memory_compact_threshold:
                logger.info(
                    "Memory compaction triggered: estimated total %d tokens "
                    "(messages: %d, summary: %d, threshold: %d), "
                    "system_prompt_msgs: %d, "
                    "compactable_msgs: %d, keep_recent_msgs: %d",
                    estimated_total_tokens,
                    estimated_message_tokens,
                    summary_tokens,
                    self.memory_compact_threshold,
                    len(system_prompt_messages),
                    len(messages_to_compact),
                    len(messages_to_keep),
                )

                self.memory_manager.add_async_summary_task(
                    messages=messages_to_compact,
                )

                compact_content = await self.memory_manager.compact_memory(
                    messages=messages_to_compact,
                    previous_summary=agent.memory.get_compressed_summary(),
                )

                await agent.memory.update_compressed_summary(compact_content)
                updated_count = await agent.memory.update_messages_mark(
                    new_mark=_MemoryMark.COMPRESSED,
                    msg_ids=[msg.id for msg in messages_to_compact],
                )
                logger.info(f"Marked {updated_count} messages as compacted")

            else:
                if (
                    self.enable_truncate_tool_result_texts
                    and messages_to_compact
                ):
                    await self.memory_manager.compact_tool_result(
                        messages_to_compact,
                    )

            # --- Hard-limit enforcement (post-compaction) ---
            await self._enforce_hard_limit(agent)

        except Exception as e:
            logger.error(
                "Failed to compact memory in pre_reasoning hook: %s",
                e,
                exc_info=True,
            )

        return None

    # ------------------------------------------------------------------
    # Hard-limit enforcement
    # ------------------------------------------------------------------

    async def _estimate_total_tokens(self, agent) -> int:
        """Re-estimate the total token count of the current context.

        Fetches uncompressed messages from memory, formats them via the
        agent's formatter and counts tokens (messages + compressed summary).
        """
        messages = await agent.memory.get_memory(
            exclude_mark=_MemoryMark.COMPRESSED,
            prepend_summary=False,
        )
        prompt = await agent.formatter.format(msgs=messages)
        message_tokens = await safe_count_message_tokens(prompt)
        summary_tokens = safe_count_str_tokens(
            agent.memory.get_compressed_summary(),
        )
        return message_tokens + summary_tokens

    async def _enforce_hard_limit(self, agent) -> None:
        """Forcibly drop oldest non-system messages until under hard limit.

        This is the safety-net that guarantees the next API call will not
        exceed the model's context window.  It only activates when
        ``hard_token_limit > 0``.

        Strategy:
        1. Re-estimate total tokens after any compaction that may have
           occurred.
        2. While over the hard limit, find the oldest non-system,
           non-compressed message and mark it as COMPRESSED (effectively
           dropping it from the active context).
        3. A maximum of ``_HARD_LIMIT_MAX_DROPS`` iterations prevents an
           infinite loop if token counting is unreliable.
        """
        if self.hard_token_limit <= 0:
            return

        estimated = await self._estimate_total_tokens(agent)
        if estimated <= self.hard_token_limit:
            return

        logger.warning(
            "Hard-limit enforcement activated: estimated %d tokens "
            "exceeds hard limit %d.  Will forcibly drop oldest messages.",
            estimated,
            self.hard_token_limit,
        )

        max_drops = _HARD_LIMIT_MAX_DROPS
        drops = 0
        while estimated > self.hard_token_limit and drops < max_drops:
            messages = await agent.memory.get_memory(
                exclude_mark=_MemoryMark.COMPRESSED,
                prepend_summary=False,
            )

            # Find the oldest non-system message to drop
            target_msg = None
            for msg in messages:
                if msg.role != "system":
                    target_msg = msg
                    break

            if target_msg is None:
                logger.error(
                    "Hard-limit enforcement: no droppable messages left "
                    "but still over limit (%d > %d).  Only system prompt "
                    "remains.",
                    estimated,
                    self.hard_token_limit,
                )
                break

            await agent.memory.update_messages_mark(
                new_mark=_MemoryMark.COMPRESSED,
                msg_ids=[target_msg.id],
            )
            drops += 1
            logger.info(
                "Hard-limit enforcement: dropped message %s (role=%s), "
                "drop #%d",
                target_msg.id,
                target_msg.role,
                drops,
            )

            # Re-estimate after dropping
            estimated = await self._estimate_total_tokens(agent)

        if estimated > self.hard_token_limit:
            logger.error(
                "Hard-limit enforcement: still over limit after %d drops "
                "(%d > %d).  The next API call may fail.",
                drops,
                estimated,
                self.hard_token_limit,
            )
        else:
            logger.info(
                "Hard-limit enforcement complete: %d messages dropped, "
                "estimated tokens now %d (limit %d).",
                drops,
                estimated,
                self.hard_token_limit,
            )
