# -*- coding: utf-8 -*-
"""Memory compaction hook for managing context window.

This hook monitors token usage and automatically compacts older messages
when the context window approaches its limit, preserving recent messages
and the system prompt.

Enhanced with compression metadata marking and session governance support.
"""
import json
import logging
import time
from typing import TYPE_CHECKING, Any

from agentscope.agent import ReActAgent
from agentscope.message import Msg, TextBlock
from copaw.constant import MEMORY_COMPACT_KEEP_RECENT

from copaw.agents.utils import (
    check_valid_messages,
    get_copaw_token_counter,
)
from copaw.config.config import load_agent_config

if TYPE_CHECKING:
    from copaw.agents.memory import MemoryManager
    from reme.memory.file_based import ReMeInMemoryMemory

logger = logging.getLogger(__name__)


class MemoryCompactionHook:
    """Hook for automatic memory compaction when context is full.

    This hook monitors the token count of messages and triggers compaction
    when it exceeds the threshold. It preserves the system prompt and recent
    messages while summarizing older conversation history.

    Enhanced features:
    - Compression metadata marking (original/new token counts, timestamp)
    - Handoff manifest generation on compression events
    """

    def __init__(self, memory_manager: "MemoryManager"):
        """Initialize memory compaction hook.

        Args:
            memory_manager: Memory manager instance for compaction
        """
        self.memory_manager = memory_manager
        self._turn_count = 0

    @staticmethod
    async def _print_status_message(
        agent: ReActAgent,
        text: str,
    ) -> None:
        """Print a status message to the agent's output."""
        msg = Msg(
            name=agent.name,
            role="assistant",
            content=[TextBlock(type="text", text=text)],
        )
        await agent.print(msg)

    def _build_compression_info(
        self,
        original_token_count: int,
        new_token_count: int,
        compacted_message_count: int,
    ) -> dict:
        """Build compression metadata dict."""
        return {
            "is_compact_summary": True,
            "compression_info": {
                "original_token_count": original_token_count,
                "new_token_count": new_token_count,
                "compacted_message_count": compacted_message_count,
                "timestamp": time.time(),
            },
        }

    async def __call__(
        self,
        agent: ReActAgent,
        kwargs: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Pre-reasoning hook to check and compact memory if needed.

        Memory structure:
            [System Prompt (preserved)] + [Compactable (counted)] +
            [Recent (preserved)]

        Args:
            agent: The agent instance
            kwargs: Input arguments to the _reasoning method

        Returns:
            None (hook doesn't modify kwargs)
        """
        self._turn_count += 1

        try:
            agent_config = load_agent_config(self.memory_manager.agent_id)
            running_config = agent_config.running
            session_config = agent_config.session
            token_counter = get_copaw_token_counter(agent_config)

            # Check max_session_turns
            if (
                session_config.max_session_turns > 0
                and self._turn_count >= session_config.max_session_turns
            ):
                await self._print_status_message(
                    agent,
                    f"⚠️ 会话已达到最大轮次限制：{session_config.max_session_turns}。"
                    f"建议使用 /new 开始新会话。",
                )

            memory: "ReMeInMemoryMemory" = agent.memory

            system_prompt = agent.sys_prompt
            compressed_summary = memory.get_compressed_summary()
            str_token_count = await token_counter.count(
                messages=[],
                text=(system_prompt or "") + (compressed_summary or ""),
            )

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
                # Auto handoff interval check (no compression needed)
                if (
                    session_config.handoff_enabled
                    and session_config.handoff_auto_interval > 0
                    and self._turn_count > 0
                    and self._turn_count % session_config.handoff_auto_interval
                    == 0
                ):
                    await self._generate_handoff(
                        agent,
                        messages,
                        "auto_interval",
                    )
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

            # Count tokens before compression
            original_token_count = await token_counter.count(
                messages=messages_to_compact,
            )

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

            # Count tokens after compression
            new_token_count = await token_counter.count(
                messages=[],
                text=compact_content or "",
            )

            # Build and log compression metadata
            if session_config.compression_mark:
                compression_info = self._build_compression_info(
                    original_token_count=original_token_count,
                    new_token_count=new_token_count,
                    compacted_message_count=len(messages_to_compact),
                )
                logger.info(
                    "Compression metadata: %s",
                    json.dumps(compression_info["compression_info"]),
                )

            await self._print_status_message(
                agent,
                f"✅ Context compaction completed "
                f"({original_token_count} → {new_token_count} tokens)",
            )

            await agent.memory.update_compressed_summary(compact_content)
            updated_count = await memory.mark_messages_compressed(
                messages_to_compact,
            )
            logger.info(f"Marked {updated_count} messages as compacted")

            # Generate handoff manifest on compression
            if session_config.handoff_enabled:
                await self._generate_handoff(
                    agent,
                    messages,
                    "compression",
                )

        except Exception as e:
            logger.exception(
                "Failed to compact memory in pre_reasoning hook: %s",
                e,
                exc_info=True,
            )

        return None

    async def _generate_handoff(
        self,
        agent: ReActAgent,
        messages: list,
        trigger: str,
    ) -> None:
        """Generate handoff manifest via HandoffHook if available.

        Args:
            agent: The agent instance
            messages: Current message list
            trigger: What triggered the handoff (compression/auto_interval)
        """
        try:
            from copaw.agents.hooks.handoff import HandoffHook

            handoff = HandoffHook(self.memory_manager)
            await handoff.generate(agent, messages, trigger=trigger)
        except ImportError:
            logger.debug(
                "HandoffHook not available, skipping handoff generation",
            )
        except Exception as e:
            logger.warning("Failed to generate handoff manifest: %s", e)
