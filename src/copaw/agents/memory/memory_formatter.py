# -*- coding: utf-8 -*-
# pylint: disable=too-many-branches
"""Memory Formatter for CoPaw agents.

Provides memory formatting capabilities including:
- Converting list of Msg to formatted string
- Memory compaction with token threshold
- Support for various content block types (text, tool_use, tool_result, etc.)
"""
import json
import logging
import os
from typing import Any

from agentscope.message import Msg

from ..utils import safe_count_str_tokens
from ..utils.tool_message_utils import _truncate_text

logger = logging.getLogger(__name__)

# Default max length for text truncation
_DEFAULT_MAX_FORMATTER_TEXT_LENGTH = 10000


class MemoryFormatter:
    """Formatter that converts list of Msg to formatted string.

    Formats messages into human-readable string representation with:
    - Role and timestamp information
    - Text content and tool calls
    - Memory compact threshold to limit total token count
    """

    def __init__(self, memory_compact_threshold: int):
        """Initialize MemoryFormatter.

        Args:
            memory_compact_threshold: Maximum token count before skipping
                older messages.
        """
        self._memory_compact_threshold = memory_compact_threshold
        self.max_length = int(
            os.environ.get(
                "MAX_FORMATTER_TEXT_LENGTH",
                _DEFAULT_MAX_FORMATTER_TEXT_LENGTH,
            ),
        )

    @staticmethod
    def _format_tool_result_output(output: str | list[dict]) -> str:
        """Convert tool result output to string.

        Args:
            output: Tool result output, either string or list of content blocks.

        Returns:
            Formatted string representation of the tool result.
        """
        if isinstance(output, str):
            return output

        textual_parts = []

        for block in output:
            try:
                if not isinstance(block, dict) or "type" not in block:
                    logger.warning(
                        "Invalid block: %s, expected a dict with 'type' key, "
                        "skipped.",
                        block,
                    )
                    continue

                block_type = block["type"]

                if block_type == "text":
                    textual_parts.append(block.get("text", ""))

                elif block_type in ["image", "audio", "video"]:
                    source = block.get("source", {})
                    url = source.get("url", "")
                    if url:
                        textual_parts.append(
                            f"[{block_type}] {url}",
                        )
                    else:
                        textual_parts.append(f"[{block_type}]")

                elif block_type == "file":
                    file_path = block.get("path", "") or block.get("url", "")
                    file_name = block.get("name", file_path)
                    textual_parts.append(f"[file] {file_name}: {file_path}")

                else:
                    # Unknown block type: log warning and skip
                    logger.warning(
                        "Unsupported block type '%s' in tool result, skipped.",
                        block_type,
                    )

            except Exception as e:
                logger.warning(
                    "Failed to process block %s: %s, skipped.",
                    block,
                    e,
                )

        if not textual_parts:
            return ""
        if len(textual_parts) == 1:
            return textual_parts[0]
        return "\n".join(f"- {part}" for part in textual_parts)

    def _format_single_msg(
        self,
        msg: Msg,
        index: int | None = None,
        add_time: bool = True,
    ) -> tuple[str, int]:
        """Format a single Msg into string representation.

        Similar to Message.format_message style.

        Args:
            msg: The Msg object to format.
            index: Optional message index for round numbering.
            add_time: Whether to include timestamp.

        Returns:
            Tuple of (formatted_string, token_count).
        """
        lines = []
        token_count = 0

        # Build header: "round{index} [{timestamp}] {role}:"
        prefix = f"round{index} " if index is not None else ""
        time_str = f"[{msg.timestamp}] " if add_time and msg.timestamp else ""
        role_str = msg.name or msg.role
        header = f"{prefix}{time_str}{role_str}:"
        lines.append(header)
        token_count += safe_count_str_tokens(header)

        # Process content blocks
        for block in msg.get_content_blocks():
            typ = block.get("type")

            if typ == "text":
                text_content = _truncate_text(block.get("text", ""), self.max_length)
                if text_content:
                    lines.append(text_content)
                    token_count += safe_count_str_tokens(text_content)

            elif typ == "thinking":
                # Skip thinking blocks to save tokens
                pass

            elif typ in ["image", "audio", "video"]:
                source = block.get("source", {})
                url = source.get("url", "")
                if url:
                    lines.append(f"[{typ}] {url}")
                else:
                    lines.append(f"[{typ}]")
                # Estimate fixed token cost for media reference
                token_count += 10

            elif typ == "tool_use":
                tool_name = block.get("name", "")
                tool_input = block.get("input", {})
                try:
                    arguments_str = json.dumps(tool_input, ensure_ascii=False)
                except (TypeError, ValueError):
                    arguments_str = str(tool_input)
                truncated_args = _truncate_text(arguments_str, self.max_length)
                tool_line = f" - tool_call={tool_name} params={truncated_args}"
                lines.append(tool_line)
                token_count += safe_count_str_tokens(tool_line)

            elif typ == "tool_result":
                tool_name = block.get("name", "")
                output = block.get("output", "")
                formatted_output = self._format_tool_result_output(output)
                truncated_output = _truncate_text(formatted_output, self.max_length)
                if truncated_output:
                    result_line = (
                        f" - tool_result={tool_name} output={truncated_output}"
                    )
                    lines.append(result_line)
                    token_count += safe_count_str_tokens(result_line)

            else:
                logger.warning(
                    "Unsupported block type %s in message, skipped.",
                    typ,
                )

        return "\n".join(lines), token_count

    def format(
        self,
        msgs: list[Msg],
        add_time: bool = True,
        add_index: bool = True,
    ) -> str:
        """Format list of Msg into a single formatted string.

        Messages are processed in reverse order (newest first) and older
        messages are skipped when token count exceeds memory_compact_threshold.

        Args:
            msgs: List of Msg objects to format.
            add_time: Whether to include timestamp in each message.
            add_index: Whether to include round index in each message.

        Returns:
            Formatted string with all messages joined by newlines.
        """
        if not msgs:
            return ""

        formatted_parts: list[str] = []
        total_token_count = 0

        # Process messages in reverse order (newest first)
        for i in range(len(msgs) - 1, -1, -1):
            msg = msgs[i]
            index = i if add_index else None

            formatted_msg, msg_token_count = self._format_single_msg(
                msg,
                index=index,
                add_time=add_time,
            )

            # Always include current message first, then check threshold
            formatted_parts.append(formatted_msg)
            total_token_count += msg_token_count

            # Check if we should stop adding older messages
            if total_token_count >= self._memory_compact_threshold:
                logger.info(
                    "Skipping older messages: token count %d >= %d",
                    total_token_count,
                    self._memory_compact_threshold,
                )
                break

        # Reverse to restore chronological order
        formatted_parts.reverse()

        return "\n\n".join(formatted_parts)
