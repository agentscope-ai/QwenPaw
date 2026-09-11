# -*- coding: utf-8 -*-
"""DashScope-native multimodal blocks that preserve documented video options.

AgentScope 2.0.2 correctly transports a ``DataBlock`` as ``video_url``, but its
stock DashScope formatter only keeps the URL.  DashScope's OpenAI-compatible
API also accepts sampling options such as ``fps`` on the content part.  Losing
that value silently restores the provider default of 2 fps, which can turn a
long public video into hundreds of thousands of unnecessary visual tokens.
"""

from __future__ import annotations

from typing import Any

from agentscope.formatter import DashScopeChatFormatter
from agentscope.message import DataBlock
from pydantic import Field


class DashScopeNativeDataBlock(DataBlock):
    """A normal AgentScope data block plus documented DashScope video knobs."""

    fps: float | None = Field(default=None, ge=0.1, le=10.0)
    min_pixels: int | None = Field(default=None, gt=0)
    max_pixels: int | None = Field(default=None, gt=0)
    total_pixels: int | None = Field(default=None, gt=0)


class DashScopeNativeFormatter(DashScopeChatFormatter):
    """Keep video sampling fields when formatting AgentScope messages."""

    def _format_dashscope_data_block(
        self,
        block: DataBlock,
    ) -> dict[str, Any] | None:
        formatted = super()._format_dashscope_data_block(block)
        if not formatted or formatted.get("type") != "video_url":
            return formatted
        for field_name in ("fps", "min_pixels", "max_pixels", "total_pixels"):
            value = getattr(block, field_name, None)
            if value is not None:
                formatted[field_name] = value
        return formatted


__all__ = ["DashScopeNativeDataBlock", "DashScopeNativeFormatter"]
