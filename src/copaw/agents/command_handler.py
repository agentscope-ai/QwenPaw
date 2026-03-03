# -*- coding: utf-8 -*-
"""Agent command handler for system commands.

This module handles system commands like /compact, /new, /clear, etc.
"""
import logging
from typing import TYPE_CHECKING

from agentscope.agent._react_agent import _MemoryMark
from agentscope.message import Msg, TextBlock

from ..config import load_config
from .utils import safe_count_message_tokens, safe_count_str_tokens

if TYPE_CHECKING:
    from .memory import MemoryManager

logger = logging.getLogger(__name__)


# pylint: disable=too-many-return-statements
def _get_block_tokens(
    block: dict,
    block_type: str,
) -> tuple[int, str]:
    """Get token count and content string for different block types.

    Args:
        block: The content block dict
        block_type: The type of the block

    Returns:
        Tuple of (token count, content string)
    """
    if block_type == "text":
        text = block.get("text", "")
        return (safe_count_str_tokens(text), text) if text else (0, "")

    if block_type == "thinking":
        thinking = block.get("thinking", "")
        return (
            (safe_count_str_tokens(thinking), thinking)
            if thinking
            else (0, "")
        )

    if block_type == "tool_use":
        # Count input dict and raw_input string
        input_dict = block.get("input", {})
        raw_input = block.get("raw_input", "")
        input_str = str(input_dict) if input_dict else ""
        total = input_str + raw_input
        return (safe_count_str_tokens(total), total) if total else (0, "")

    if block_type == "tool_result":
        output = block.get("output")
        if isinstance(output, str):
            return (
                (safe_count_str_tokens(output), output) if output else (0, "")
            )
        if isinstance(output, list):
            # Recursively count tokens in nested blocks
            total_tokens = 0
            total_str = ""
            for item in output:
                if isinstance(item, dict):
                    item_type = item.get("type", "unknown")
                    item_tokens, item_str = _get_block_tokens(item, item_type)
                    total_tokens += item_tokens
                    total_str += item_str
            return (total_tokens, total_str)
        return (0, "")

    if block_type in ("image", "audio", "video"):
        # For media blocks, count the URL or indicate base64 size
        source = block.get("source", {})
        if source.get("type") == "url":
            url = source.get("url", "")
            return (safe_count_str_tokens(url), url)
        if source.get("type") == "base64":
            # Base64 data can be large, return approximate token count
            data = source.get("data", "")
            return (len(data) // 4, "[base64]") if data else (0, "")
        return (0, "")

    return (0, "")


class CommandHandler:
    """Handler for agent system commands."""

    # Supported system commands
    SYSTEM_COMMANDS = frozenset(
        {
            "start",
            "compact",
            "new",
            "clear",
            "history",
            "compact_str",
            "await_summary",
        },
    )

    def __init__(
        self,
        agent_name: str,
        memory,
        formatter,
        memory_manager: "MemoryManager | None" = None,
        enable_memory_manager: bool = True,
    ):
        """Initialize command handler.

        Args:
            agent_name: Name of the agent for message creation
            memory: Agent's memory instance
            formatter: Agent's formatter instance for message formatting
            memory_manager: Optional memory manager instance
            enable_memory_manager: Whether memory manager is enabled
        """
        self.agent_name = agent_name
        self.memory = memory
        self.formatter = formatter
        self.memory_manager = memory_manager
        self._enable_memory_manager = enable_memory_manager

    def is_command(self, query: str | None) -> bool:
        """Check if the query is a system command.

        Args:
            query: User query string

        Returns:
            True if query is a system command
        """
        if not isinstance(query, str) or not query.startswith("/"):
            return False
        return query.strip().lstrip("/") in self.SYSTEM_COMMANDS

    async def _make_system_msg(self, text: str) -> Msg:
        """Create a system response message.

        Args:
            text: Message text content

        Returns:
            System message
        """
        return Msg(
            name=self.agent_name,
            role="assistant",
            content=[TextBlock(type="text", text=text)],
        )

    def _has_memory_manager(self) -> bool:
        """Check if memory manager is available."""
        return self._enable_memory_manager and self.memory_manager is not None

    async def _mark_messages_compressed(self, messages: list[Msg]) -> int:
        """Mark messages as compressed and return count."""
        return await self.memory.update_messages_mark(
            new_mark=_MemoryMark.COMPRESSED,
            msg_ids=[msg.id for msg in messages],
        )

    async def _process_start(self, messages: list[Msg]) -> Msg:
        """Process /start command - same as /new."""
        if not messages:
            await self.memory.update_compressed_summary("")
            return await self._make_system_msg(
                "**Welcome!**\n\n"
                "- This is a fresh conversation\n"
                "- Ready to help you!",
            )
        if not self._has_memory_manager():
            return await self._make_system_msg(
                "**Memory Manager Disabled**\n\n"
                "- Cannot start new conversation with summary\n"
                "- Enable memory manager to use this feature",
            )

        self.memory_manager.add_async_summary_task(messages=messages)
        await self.memory.update_compressed_summary("")
        updated_count = await self._mark_messages_compressed(messages)
        logger.info(f"Marked {updated_count} messages as compacted")
        return await self._make_system_msg(
            "**New Conversation Started!**\n\n"
            "- Summary task started in background\n"
            "- Ready for new conversation",
        )

    async def _process_compact(self, messages: list[Msg]) -> Msg:
        """Process /compact command."""
        if not messages:
            return await self._make_system_msg(
                "**No messages to compact.**\n\n"
                "- Current memory is empty\n"
                "- No action taken",
            )
        if not self._has_memory_manager():
            return await self._make_system_msg(
                "**Memory Manager Disabled**\n\n"
                "- Memory compaction is not available\n"
                "- Enable memory manager to use this feature",
            )

        self.memory_manager.add_async_summary_task(messages=messages)
        compact_content = await self.memory_manager.compact_memory(
            messages_to_summarize=messages,
            previous_summary=self.memory.get_compressed_summary(),
        )
        await self.memory.update_compressed_summary(compact_content)
        updated_count = await self._mark_messages_compressed(messages)
        logger.info(
            f"Marked {updated_count} messages as compacted "
            f"with:\n{compact_content}",
        )
        return await self._make_system_msg(
            f"**Compact Complete!**\n\n"
            f"- Messages compacted: {updated_count}\n"
            f"**Compressed Summary:**\n{compact_content}\n"
            f"- Summary task started in background\n",
        )

    async def _process_new(self, messages: list[Msg]) -> Msg:
        """Process /new command."""
        if not messages:
            await self.memory.update_compressed_summary("")
            return await self._make_system_msg(
                "**No messages to summarize.**\n\n"
                "- Current memory is empty\n"
                "- Compressed summary is clear\n"
                "- No action taken",
            )
        if not self._has_memory_manager():
            return await self._make_system_msg(
                "**Memory Manager Disabled**\n\n"
                "- Cannot start new conversation with summary\n"
                "- Enable memory manager to use this feature",
            )

        self.memory_manager.add_async_summary_task(messages=messages)
        await self.memory.update_compressed_summary("")
        updated_count = await self._mark_messages_compressed(messages)
        logger.info(f"Marked {updated_count} messages as compacted")
        return await self._make_system_msg(
            "**New Conversation Started!**\n\n"
            "- Summary task started in background\n"
            "- Ready for new conversation",
        )

    async def _process_clear(self, _messages: list[Msg]) -> Msg:
        """Process /clear command."""
        self.memory.content.clear()
        await self.memory.update_compressed_summary("")
        return await self._make_system_msg(
            "**History Cleared!**\n\n"
            "- Compressed summary reset\n"
            "- Memory is now empty",
        )

    async def _process_compact_str(self, _messages: list[Msg]) -> Msg:
        """Process /compact_str command to show compressed summary."""
        summary = self.memory.get_compressed_summary()
        if not summary:
            return await self._make_system_msg(
                "**No Compressed Summary**\n\n"
                "- No summary has been generated yet\n"
                "- Use /compact or wait for auto-compaction",
            )
        return await self._make_system_msg(
            f"**Compressed Summary**\n\n{summary}",
        )

    async def _process_history(self, messages: list[Msg]) -> Msg:
        """Process /history command."""

        compressed_summary = self.memory.get_compressed_summary() or ""
        compressed_summary_tokens = safe_count_str_tokens(compressed_summary)

        # Calculate total token count using formatter
        prompt = await self.formatter.format(msgs=messages)
        messages_tokens = await safe_count_message_tokens(prompt)
        estimated_tokens = messages_tokens + compressed_summary_tokens

        # Get max_input_length from config and calculate context usage ratio
        config = load_config()
        max_input_length = config.agents.running.max_input_length
        context_usage_ratio = (
            (estimated_tokens / max_input_length * 100)
            if max_input_length > 0
            else 0
        )

        lines = []
        for i, msg in enumerate(messages, 1):
            try:
                # Content blocks info and total tokens calculation
                content = msg.content
                if isinstance(content, str):
                    text_tokens = safe_count_str_tokens(content)
                    seq_blocks = ""
                    preview = (
                        f"{content[:100]}..."
                        if len(content) > 100
                        else content
                    )
                else:
                    block_infos = []
                    total_tokens = 0
                    text_parts = []
                    for block in content:
                        block_type = block.get("type", "unknown")
                        block_tokens, block_str = _get_block_tokens(
                            block,
                            block_type,
                        )
                        total_tokens += block_tokens
                        text_parts.append(block_str)
                        block_infos.append(
                            f"{block_type}(tokens={block_tokens})",
                        )
                    text_tokens = total_tokens
                    seq_blocks = f"\n    content: [{', '.join(block_infos)}]"
                    text_preview = "".join(text_parts)
                    preview = (
                        f"{text_preview[:100]}..."
                        if len(text_preview) > 100
                        else text_preview
                    )
            except Exception as e:
                text_tokens = 0
                seq_blocks = ""
                preview = f"<error: {e}>"
            lines.append(
                f"[{i}] **{msg.role}** (text_tokens={text_tokens})"
                f"{seq_blocks}\n    preview: {preview}",
            )

        return await self._make_system_msg(
            f"**Conversation History**\n\n"
            f"- Total messages: {len(messages)}\n"
            f"- Estimated tokens: {estimated_tokens}\n"
            f"- Max input length: {max_input_length}\n"
            f"- Context usage: {context_usage_ratio:.1f}%\n"
            f"- Compressed summary tokens: {compressed_summary_tokens}\n\n"
            + "\n\n".join(lines),
        )

    async def _process_await_summary(self, _messages: list[Msg]) -> Msg:
        """Process /await_summary command to wait for all summary tasks."""
        if not self._has_memory_manager():
            return await self._make_system_msg(
                "**Memory Manager Disabled**\n\n"
                "- Cannot await summary tasks\n"
                "- Enable memory manager to use this feature",
            )

        task_count = len(self.memory_manager.summary_tasks)
        if task_count == 0:
            return await self._make_system_msg(
                "**No Summary Tasks**\n\n"
                "- No pending summary tasks to wait for",
            )

        result = await self.memory_manager.await_summary_tasks()
        return await self._make_system_msg(
            f"**Summary Tasks Complete**\n\n"
            f"- Waited for {task_count} summary task(s)\n"
            f"- {result}"
            f"- All tasks have finished",
        )

    async def handle_command(self, query: str) -> Msg:
        """Process system commands.

        Args:
            query: Command string (e.g., "/compact", "/new")

        Returns:
            System response message

        Raises:
            RuntimeError: If command is not recognized
        """
        messages = await self.memory.get_memory(
            exclude_mark=_MemoryMark.COMPRESSED,
            prepend_summary=False,
        )
        command = query.strip().lstrip("/")
        logger.info(f"Processing command: {command}")

        handler = getattr(self, f"_process_{command}", None)
        if handler is None:
            raise RuntimeError(f"Unknown command: {query}")
        return await handler(messages)
