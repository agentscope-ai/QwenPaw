# -*- coding: utf-8 -*-
"""Schema definitions for AgentScope message statistics."""

from pydantic import BaseModel, Field

from ...constant import TRUNCATION_NOTICE_MARKER

_DEFAULT_MAX_BLOCK_TEXT_PREVIEW_LENGTH = 100
_DEFAULT_MAX_FORMATTER_TEXT_LENGTH = 1000


class AsBlockStat(BaseModel):
    """Statistics and metadata for a single content
    block in an AgentScope message."""

    block_type: str = Field(default=...)
    text: str = Field(default="", description="Text content of the block")
    token_count: int = Field(
        default=0,
        description="Token count of the block, including base64 data",
    )

    # For tool_use and tool_result blocks
    tool_name: str = Field(
        default="",
        description="Tool name for tool_use/tool_result blocks",
    )
    tool_input: str = Field(
        default="",
        description="Tool input arguments for tool_use blocks",
    )
    tool_output: str = Field(
        default="",
        description="Tool output for tool_result blocks",
    )

    # For media blocks
    media_url: str = Field(
        default="",
        description="URL for image/audio/video blocks",
    )

    @property
    def preview(self) -> str:
        """Return a short preview of the block content."""
        return self.format(_DEFAULT_MAX_BLOCK_TEXT_PREVIEW_LENGTH)

    def _truncate(self, text: str, max_length: int) -> str:
        """Truncate text with ellipsis, replacing newlines with spaces."""
        text = text.replace("\n", " ")
        if len(text) <= max_length:
            return text
        return text[:max_length] + "..."

    # pylint: disable=too-many-return-statements
    def format(
        self,
        max_length: int = _DEFAULT_MAX_FORMATTER_TEXT_LENGTH,
        include_thinking: bool = True,
    ) -> str:
        """Format block content to string representation.

        Args:
            max_length: Maximum length of text content in the output.
            include_thinking: Whether to include thinking block content.

        Returns:
            Formatted string representation of the block.
        """
        if self.block_type == "text":
            if not self.text:
                return ""
            return f"[text]: {self._truncate(self.text, max_length)}"
        if self.block_type == "thinking":
            if not include_thinking or not self.text:
                return ""
            return f"[think]: {self._truncate(self.text, max_length)}"
        if self.block_type in ("image", "audio", "video"):
            content = self.media_url if self.media_url else ""
            return f"[{self.block_type}]: {content}"
        if self.block_type == "tool_use":
            content = (
                f"{self.tool_name} params="
                f"{self._truncate(self.tool_input, max_length)}"
            )
            return f"[tool_use]: {content}"
        if self.block_type == "tool_result":
            if not self.tool_output:
                return ""
            display_output = self.tool_output.split(TRUNCATION_NOTICE_MARKER)[
                0
            ]
            content = (
                f"{self.tool_name} output="
                f"{self._truncate(display_output, max_length)}"
            )
            return f"[tool_result]: {content}"
        return ""


class AsMsgStat(BaseModel):
    """Statistics and metadata for a complete AgentScope message."""

    name: str = Field(default=...)
    role: str = Field(default="")
    content: list[AsBlockStat] = Field(default_factory=list)
    timestamp: str = Field(default="")
    metadata: dict = Field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        """Return the total token count across all content blocks."""
        return sum(block.token_count for block in self.content)

    @property
    def preview(self) -> str:
        """Return a short preview of the message content."""
        return self.format(_DEFAULT_MAX_BLOCK_TEXT_PREVIEW_LENGTH)

    def format(
        self,
        max_length: int = _DEFAULT_MAX_FORMATTER_TEXT_LENGTH,
        include_thinking: bool = True,
    ) -> str:
        """Format message to string representation."""
        time_str = f"[{self.timestamp}] " if self.timestamp else ""
        header = f"{time_str}{self.name or self.role}:"
        blocks = [
            block.format(max_length, include_thinking)
            for block in self.content
        ]
        return "\n".join([header] + [b for b in blocks if b])
