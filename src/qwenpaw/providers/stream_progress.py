# -*- coding: utf-8 -*-
"""Shared stream-progress semantics for model wrappers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from agentscope.message import (
    Base64Source,
    DataBlock,
    TextBlock,
    ThinkingBlock,
    ToolCallBlock,
    URLSource,
)


def _mapping_has_meaningful_content(block: Mapping[str, Any]) -> bool:
    """Return whether a serialized content block carries real payload."""
    block_type = block.get("type")
    if block_type == "text":
        return bool(block.get("text"))
    if block_type == "thinking":
        return bool(block.get("thinking"))
    if block_type in {"tool_call", "tool_use"}:
        return bool(block.get("name") or block.get("input"))
    if block_type == "data":
        source = block.get("source")
        if isinstance(source, Mapping):
            return bool(source.get("data") or source.get("url"))
        return bool(block.get("data") or block.get("url"))
    return bool(block)


def _block_has_meaningful_content(block: Any) -> bool:
    """Return whether one native or serialized block carries payload."""
    if isinstance(block, TextBlock):
        meaningful = bool(block.text)
    elif isinstance(block, ThinkingBlock):
        meaningful = bool(block.thinking)
    elif isinstance(block, ToolCallBlock):
        meaningful = bool(block.name or block.input)
    elif isinstance(block, DataBlock):
        if isinstance(block.source, Base64Source):
            meaningful = bool(block.source.data)
        elif isinstance(block.source, URLSource):
            meaningful = bool(block.source.url)
        else:
            meaningful = False
    elif isinstance(block, Mapping):
        meaningful = _mapping_has_meaningful_content(block)
    else:
        meaningful = bool(block)
    return meaningful


def has_meaningful_stream_content(content: Any) -> bool:
    """Return whether stream content represents visible model progress."""
    if isinstance(content, Sequence) and not isinstance(
        content,
        (str, bytes, bytearray),
    ):
        return any(_block_has_meaningful_content(block) for block in content)
    return _block_has_meaningful_content(content)
