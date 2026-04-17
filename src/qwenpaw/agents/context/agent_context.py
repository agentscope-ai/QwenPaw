"""Custom memory implementation with bugfixes and extensions."""

import json
from datetime import datetime
from pathlib import Path

import aiofiles
import aiofiles.os

from agentscope.agent._react_agent import _MemoryMark  # noqa
from agentscope.memory import InMemoryMemory
from agentscope.message import Msg

from ..utils.estimate_token_counter import EstimatedTokenCounter
from .as_msg_handler import AsMsgHandler
import logging


logger = logging.getLogger(__name__)


_SUMMARY_PROMPT_TEMPLATE = """# Summary of previous conversation
Previous conversation logs are offloaded to dialog/YYYY-MM-DD.jsonl (or nearby date files). 
Here is the summary:
{summary}
The above is a summary of previous conversation, use it as context to maintain continuity."""


class AgentContext(InMemoryMemory):
    """Extended InMemoryMemory with bugfixes and summary support."""

    def __init__(
        self,
        token_counter: EstimatedTokenCounter,
        dialog_path: str | Path | None = None,
    ):
        """Initialize the AgentContext.

        Args:
            token_counter: Token counter for measuring content length.
            dialog_path: Path to the dialog storage directory. If provided,
                messages will be persisted to jsonl files when cleared or compressed.
        """
        super().__init__()
        self._token_counter: EstimatedTokenCounter = token_counter
        self._msg_handler: AsMsgHandler = AsMsgHandler(token_counter)
        self._dialog_path: Path | None = Path(dialog_path) if dialog_path else None

    async def _append_messages_to_dialog(self, messages: list[Msg]) -> int:
        """Append messages to dialog storage file.

        Saves messages to jsonl files named by message date (YYYY-mm-dd.jsonl).
        Each line is a JSON representation of a message.
        Messages are grouped by their timestamp date.

        Args:
            messages: List of messages to append to the dialog file.

        Returns:
            Number of messages successfully appended.
        """
        if not messages:
            return 0

        if self._dialog_path is None:
            logger.warning("dialog_path is not set, skipping dialog persistence")
            return 0

        # Ensure dialog directory exists
        try:
            await aiofiles.os.makedirs(self._dialog_path, exist_ok=True)
        except Exception as e:
            logger.exception(f"Failed to create dialog directory {self._dialog_path}: {e}")
            return 0

        # Group messages by date (extracted from timestamp)
        # timestamp format: "YYYY-mm-dd HH:MM:SS.fff"
        messages_by_date: dict[str, list[Msg]] = {}
        for msg in messages:
            try:
                if msg.timestamp:
                    # Extract date part from timestamp
                    date_str = msg.timestamp.split()[0]  # "YYYY-mm-dd"
                else:
                    date_str = datetime.now().strftime("%Y-%m-%d")

                if date_str not in messages_by_date:
                    messages_by_date[date_str] = []
                messages_by_date[date_str].append(msg)
            except Exception as e:
                logger.warning(f"Failed to process message timestamp: {e}, using today's date")
                date_str = datetime.now().strftime("%Y-%m-%d")
                if date_str not in messages_by_date:
                    messages_by_date[date_str] = []
                messages_by_date[date_str].append(msg)

        # Append messages to corresponding date files (sorted by timestamp within each date)
        total_count = 0
        for date_str, msgs in messages_by_date.items():
            # Sort messages by timestamp within the same date
            try:
                msgs_sorted = sorted(msgs, key=lambda m: m.timestamp or "")
            except Exception as e:
                logger.warning(f"Failed to sort messages by timestamp: {e}")
                msgs_sorted = msgs

            filename = f"{date_str}.jsonl"
            filepath = self._dialog_path / filename

            try:
                async with aiofiles.open(filepath, mode="a", encoding="utf-8") as f:
                    for msg in msgs_sorted:
                        msg_dict = msg.to_dict()
                        await f.write(json.dumps(msg_dict, ensure_ascii=False) + "\n")
                        total_count += 1
                logger.info(f"Appended {len(msgs_sorted)} messages to {filepath}")
            except Exception as e:
                logger.exception(f"Failed to append messages to dialog file {filepath}: {e}")

        return total_count

    async def get_memory(
        self,
        prepend_summary: bool = True,
        **_kwargs,
    ) -> list[Msg]:
        """Get the messages from the memory by mark (if provided).

        Args:
            prepend_summary: Whether to prepend compressed summary
            **_kwargs: Additional keyword arguments (ignored)

        Returns:
            List of filtered messages
        """
        filtered_content = [(msg, marks) for msg, marks in self.content if _MemoryMark.COMPRESSED not in marks]

        if prepend_summary and self._compressed_summary:
            return [
                Msg(
                    "user",
                    _SUMMARY_PROMPT_TEMPLATE.format(summary=self._compressed_summary),
                    "user",
                ),
                *[msg for msg, _ in filtered_content],
            ]

        return [msg for msg, _ in filtered_content]

    def get_compressed_summary(self) -> str:
        """Get the compressed summary of the memory."""
        return self._compressed_summary

    def state_dict(self) -> dict:
        """Get the state dictionary for serialization."""
        return {
            "content": [[msg.to_dict(), marks] for msg, marks in self.content],
            "_compressed_summary": self._compressed_summary,
        }

    # pylint: disable=attribute-defined-outside-init
    def load_state_dict(self, state_dict: dict, strict: bool = True) -> None:
        """Load the state dictionary for deserialization."""
        if strict and "content" not in state_dict:
            raise KeyError("The state_dict does not contain 'content' key required for InMemoryMemory.")

        self.content = []  # pylint: disable=attribute-defined-outside-init
        for item in state_dict.get("content", []):
            if isinstance(item, (tuple, list)) and len(item) == 2:
                msg_dict, marks = item
                msg = Msg.from_dict(msg_dict)
                self.content.append((msg, marks))

            elif isinstance(item, dict):
                # For compatibility with older versions
                msg = Msg.from_dict(item)
                self.content.append((msg, []))

            else:
                raise ValueError("Invalid item format in state_dict for InMemoryMemory.")

        self._compressed_summary = state_dict.get("_compressed_summary", "")

    async def mark_messages_compressed(self, messages: list[Msg]) -> int:
        """Mark messages as compressed, persist them to dialog, and remove from memory.

        This method:
        1. Persists the given messages to the dialog storage
        2. Removes them from memory

        Args:
            messages: List of messages to mark as compressed.

        Returns:
            Number of messages marked as compressed.
        """
        if not messages:
            return 0

        # Persist messages to dialog storage instead of compressed
        await self._append_messages_to_dialog(messages)

        # Remove messages from memory
        msg_ids = {msg.id for msg in messages}
        initial_size = len(self.content)
        self.content = [(msg, marks) for msg, marks in self.content if msg.id not in msg_ids]
        removed_count = initial_size - len(self.content)

        logger.info(f"Marked {removed_count} messages as compressed and removed from memory")
        return removed_count

    def clear_compressed_summary(self):
        """Clear the compressed summary."""
        self._compressed_summary = ""  # pylint: disable=attribute-defined-outside-init

    async def clear_content(self):
        """Persist all messages to dialog storage and clear the content.

        This method:
        1. Persists all messages in memory to the dialog storage
        2. Clears the in-memory content
        """
        # Persist all messages to dialog storage
        if self.content:
            messages = [msg for msg, _ in self.content]
            await self._append_messages_to_dialog(messages)

        # Clear in-memory content
        self.content.clear()
        logger.info("Cleared all messages from memory")

    async def estimate_tokens(self, max_input_length: int) -> dict:
        """Estimate token usage for current memory.

        Args:
            max_input_length: Max input length for context usage calculation.

        Returns:
            Dict containing detailed token statistics:
            - total_messages: Number of messages
            - compressed_summary_tokens: Tokens in compressed summary
            - messages_tokens: Tokens in messages
            - estimated_tokens: Total estimated tokens
            - max_input_length: Max input length from config
            - context_usage_ratio: Usage percentage
            - messages_detail: List of per-message AsMsgStat objects
        """
        messages = await self.get_memory(prepend_summary=False)

        compressed_summary = self.get_compressed_summary()
        compressed_summary_tokens = await self._msg_handler.count_str_token(compressed_summary)

        # Build per-message token details using AsMsgHandler
        messages_detail = [await self._msg_handler.stat_message(msg) for msg in messages]

        # Calculate total message tokens from stats
        messages_tokens = sum(stat.total_tokens for stat in messages_detail)
        estimated_tokens = messages_tokens + compressed_summary_tokens

        # Calculate context usage ratio
        context_usage_ratio = (estimated_tokens / max_input_length * 100) if max_input_length > 0 else 0

        return {
            "total_messages": len(messages),
            "compressed_summary_tokens": compressed_summary_tokens,
            "messages_tokens": messages_tokens,
            "estimated_tokens": estimated_tokens,
            "max_input_length": max_input_length,
            "context_usage_ratio": context_usage_ratio,
            "messages_detail": messages_detail,
        }

    async def get_history_str(self, max_input_length: int) -> str:
        """Get formatted history string similar to /history command output.

        Args:
            max_input_length: Max input length for context usage calculation.

        Returns:
            Formatted string containing conversation history details
        """
        stats = await self.estimate_tokens(max_input_length)

        lines = []
        for i, msg_stat in enumerate(stats["messages_detail"], 1):
            blocks_info = ""
            if msg_stat.content:
                block_strs = [f"{b.block_type}(tokens={b.token_count})" for b in msg_stat.content]
                blocks_info = f"\n    content: [{', '.join(block_strs)}]"

            lines.append(
                f"[{i}] **{msg_stat.role}** "
                f"(total_tokens={msg_stat.total_tokens})"
                f"{blocks_info}\n    preview: {msg_stat.preview}",
            )

        return (
            f"**Conversation History**\n\n"
            f"- Total messages: {stats['total_messages']}\n"
            f"- Estimated tokens: {stats['estimated_tokens']}\n"
            f"- Max input length: {stats['max_input_length']}\n"
            f"- Context usage: {stats['context_usage_ratio']:.1f}%\n"
            f"- Compressed summary tokens: {stats['compressed_summary_tokens']}\n\n" + "\n\n".join(lines)
        )
