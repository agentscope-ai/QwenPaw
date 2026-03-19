# -*- coding: utf-8 -*-
"""Agent command handler for system commands.

This module handles system commands like /compact, /new, /clear, etc.
"""
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from agentscope.message import Msg, TextBlock

from ..config.config import load_agent_config
from ..constant import DEBUG_HISTORY_FILE, MAX_LOAD_HISTORY_COUNT

if TYPE_CHECKING:
    from .memory import MemoryManager
    from reme.memory.file_based import ReMeInMemoryMemory

logger = logging.getLogger(__name__)


class ConversationCommandHandlerMixin:
    """Mixin for conversation (system) commands: /compact, /new, /clear, etc.

    Expects self to have: agent_name, memory, formatter, memory_manager,
    _enable_memory_manager.
    """

    # Supported conversation commands (unchanged set)
    SYSTEM_COMMANDS = frozenset(
        {
            "compact",
            "new",
            "clear",
            "history",
            "compact_str",
            "await_summary",
            "message",
            "dump_history",
            "load_history",
        },
    )

    def is_conversation_command(self, query: str | None) -> bool:
        """Check if the query is a conversation system command.

        Args:
            query: User query string

        Returns:
            True if query is a system command
        """
        if not isinstance(query, str) or not query.startswith("/"):
            return False
        return query.strip().lstrip("/") in self.SYSTEM_COMMANDS


class CommandHandler(ConversationCommandHandlerMixin):
    """Handler for system commands (uses ConversationCommandHandlerMixin)."""

    def __init__(
        self,
        agent_name: str,
        memory: "ReMeInMemoryMemory",
        memory_manager: "MemoryManager | None" = None,
        enable_memory_manager: bool = True,
    ):
        """Initialize command handler.

        Args:
            agent_name: Name of the agent for message creation
            memory: Agent's ReMeInMemoryMemory instance
            memory_manager: Optional memory manager instance
            enable_memory_manager: Whether memory manager is enabled
        """
        self.agent_name = agent_name
        self.memory = memory
        self.memory_manager = memory_manager
        self._enable_memory_manager = enable_memory_manager

    def _get_agent_config(self):
        """Get hot-reloaded agent config.

        Returns:
            AgentProfileConfig: The current agent configuration
        """
        return load_agent_config(self.memory_manager.agent_id)

    def is_command(self, query: str | None) -> bool:
        """Check if the query is a system command (alias for mixin)."""
        return self.is_conversation_command(query)

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

    async def _process_compact(
        self,
        messages: list[Msg],
        _args: str = "",
    ) -> Msg:
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
            messages=messages,
            previous_summary=self.memory.get_compressed_summary(),
        )
        await self.memory.update_compressed_summary(compact_content)
        updated_count = len(messages)
        self.memory.clear_content()
        return await self._make_system_msg(
            f"**Compact Complete!**\n\n"
            f"- Messages compacted: {updated_count}\n"
            f"**Compressed Summary:**\n{compact_content}\n"
            f"- Summary task started in background\n",
        )

    async def _process_new(self, messages: list[Msg], _args: str = "") -> Msg:
        """Process /new command."""
        if not messages:
            self.memory.clear_compressed_summary()
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
        self.memory.clear_compressed_summary()

        self.memory.clear_content()
        return await self._make_system_msg(
            "**New Conversation Started!**\n\n"
            "- Summary task started in background\n"
            "- Ready for new conversation",
        )

    async def _process_clear(
        self,
        _messages: list[Msg],
        _args: str = "",
    ) -> Msg:
        """Process /clear command."""
        self.memory.clear_content()
        self.memory.clear_compressed_summary()
        return await self._make_system_msg(
            "**History Cleared!**\n\n"
            "- Compressed summary reset\n"
            "- Memory is now empty",
        )

    async def _process_compact_str(
        self,
        _messages: list[Msg],
        _args: str = "",
    ) -> Msg:
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

    async def _process_history(
        self,
        _messages: list[Msg],
        _args: str = "",
    ) -> Msg:
        """Process /history command."""
        agent_config = self._get_agent_config()
        running_config = agent_config.running
        history_str = await self.memory.get_history_str(
            max_input_length=running_config.max_input_length,
        )

        # Truncate if too long
        if len(history_str) > running_config.history_max_length:
            half = running_config.history_max_length // 2
            history_str = f"{history_str[:half]}\n...\n{history_str[-half:]}"

        history_str += (
            "\n\n---\n\n- Use /message <index> to view full message content"
        )

        # Add compact summary hint if available
        if self.memory.get_compressed_summary():
            history_str += "\n- Use /compact_str to view full compact summary"

        return await self._make_system_msg(history_str)

    async def _process_await_summary(
        self,
        _messages: list[Msg],
        _args: str = "",
    ) -> Msg:
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

    async def _process_message(
        self,
        messages: list[Msg],
        args: str = "",
    ) -> Msg:
        """Process /message x command to show the nth message.

        Args:
            messages: List of messages in memory
            args: Command arguments (message index)

        Returns:
            System message with the requested message content
        """
        agent_config = self._get_agent_config()
        history_max_length = agent_config.running.history_max_length

        if not args:
            return await self._make_system_msg(
                "**Usage: /message <index>**\n\n"
                "- Example: /message 1 (show first message)\n"
                f"- Available messages: 1 to {len(messages)}",
            )

        try:
            index = int(args.strip())
        except ValueError:
            return await self._make_system_msg(
                f"**Invalid Index: '{args}'**\n\n"
                "- Index must be a number\n"
                "- Example: /message 1",
            )

        if not messages:
            return await self._make_system_msg(
                "**No Messages Available**\n\n- Current memory is empty",
            )

        if index < 1 or index > len(messages):
            return await self._make_system_msg(
                f"**Index Out of Range: {index}**\n\n"
                f"- Available range: 1 to {len(messages)}\n"
                f"- Example: /message 1",
            )

        msg = messages[index - 1]

        # Handle content display with truncation
        content_str = str(msg.content)
        truncated = False
        if len(content_str) > history_max_length:
            half = history_max_length // 2
            content_str = f"{content_str[:half]}\n...\n{content_str[-half:]}"
            truncated = True

        truncation_hint = (
            "\n\n- Content truncated, use /dump_history to view full content"
            if truncated
            else ""
        )
        return await self._make_system_msg(
            f"**Message {index}/{len(messages)}**\n\n"
            f"- **Timestamp:** {msg.timestamp}\n"
            f"- **Name:** {msg.name}\n"
            f"- **Role:** {msg.role}\n"
            f"- **Content:**\n{content_str}{truncation_hint}",
        )

    async def _process_dump_history(
        self,
        messages: list[Msg],
        _args: str = "",
    ) -> Msg:
        """Process /dump_history command to save messages to a JSONL file.

        Args:
            messages: List of messages in memory
            _args: Command arguments (unused)

        Returns:
            System message with dump result
        """
        agent_config = self._get_agent_config()
        history_file = Path(agent_config.workspace_dir) / DEBUG_HISTORY_FILE

        try:
            # Check if there's a compressed summary
            compressed_summary = self.memory.get_compressed_summary()
            has_summary = bool(compressed_summary)

            # Build dump messages: summary first (if exists), then messages
            dump_messages = []
            if has_summary:
                summary_msg = Msg(
                    name="user",
                    role="user",
                    content=[TextBlock(type="text", text=compressed_summary)],
                    metadata={"has_compressed_summary": "true"},
                )
                dump_messages.append(summary_msg)

            dump_messages.extend(messages)

            with open(history_file, "w", encoding="utf-8") as f:
                for msg in dump_messages:
                    f.write(
                        json.dumps(msg.to_dict(), ensure_ascii=False) + "\n",
                    )

            logger.info(
                f"Dumped {len(dump_messages)} messages to {history_file}",
            )
            return await self._make_system_msg(
                f"**History Dumped!**\n\n"
                f"- Messages saved: {len(dump_messages)}\n"
                f"- Has summary: {has_summary}\n"
                f"- File: `{history_file}`",
            )
        except Exception as e:
            logger.exception(f"Failed to dump history: {e}")
            return await self._make_system_msg(
                f"**Dump Failed**\n\n" f"- Error: {e}",
            )

    async def _process_load_history(
        self,
        _messages: list[Msg],
        _args: str = "",
    ) -> Msg:
        """Process /load_history command to load messages from a JSONL file.

        Args:
            _messages: List of messages in memory (unused)
            _args: Command arguments (unused)

        Returns:
            System message with load result
        """
        agent_config = self._get_agent_config()
        history_file = Path(agent_config.workspace_dir) / DEBUG_HISTORY_FILE

        if not history_file.exists():
            return await self._make_system_msg(
                f"**Load Failed**\n\n"
                f"- File not found: `{history_file}`\n"
                f"- Use /dump_history first to create the file",
            )

        try:
            loaded_messages: list[Msg] = []
            has_summary_marker = False
            with open(history_file, encoding="utf-8") as f:
                for i, line in enumerate(f):
                    line = line.strip()
                    if line:
                        msg_dict = json.loads(line)
                        msg = Msg.from_dict(msg_dict)
                        loaded_messages.append(msg)
                        # Check first message for summary marker
                        if (
                            i == 0
                            and msg.metadata.get("has_compressed_summary")
                            == "true"
                        ):
                            has_summary_marker = True
                        if len(loaded_messages) >= MAX_LOAD_HISTORY_COUNT:
                            break

            # Clear existing memory
            self.memory.content.clear()
            self.memory.clear_compressed_summary()

            # If first message has summary marker, extract and restore summary
            if has_summary_marker and loaded_messages:
                summary_msg = loaded_messages.pop(0)
                # Extract summary content from the message
                summary_content = summary_msg.get_text_content() or ""
                # Set the compressed summary directly
                await self.memory.update_compressed_summary(summary_content)
                logger.info("Restored compressed summary from history file")

            for msg in loaded_messages:
                await self.memory.add(msg)

            logger.info(
                f"Loaded {len(loaded_messages)} messages from {history_file}",
            )
            return await self._make_system_msg(
                f"**History Loaded!**\n\n"
                f"- Messages loaded: {len(loaded_messages)}\n"
                f"- Has summary: {has_summary_marker}\n"
                f"- File: `{history_file}`\n"
                f"- Memory cleared before loading",
            )
        except Exception as e:
            logger.exception(f"Failed to load history: {e}")
            return await self._make_system_msg(
                f"**Load Failed**\n\n" f"- Error: {e}",
            )

    async def handle_conversation_command(self, query: str) -> Msg:
        """Process conversation system commands.

        Args:
            query: Command string (e.g., "/compact", "/new", "/message 5")

        Returns:
            System response message

        Raises:
            RuntimeError: If command is not recognized
        """
        messages = await self.memory.get_memory(
            prepend_summary=False,
        )
        # Parse command and arguments
        parts = query.strip().lstrip("/").split(" ", maxsplit=1)
        command = parts[0]
        args = parts[1] if len(parts) > 1 else ""
        logger.info(f"Processing command: {command}, args: {args}")

        handler = getattr(self, f"_process_{command}", None)
        if handler is None:
            raise RuntimeError(f"Unknown command: {query}")
        return await handler(messages, args)

    async def handle_command(self, query: str) -> Msg:
        """Process system commands (alias for handle_conversation_command)."""
        return await self.handle_conversation_command(query)
