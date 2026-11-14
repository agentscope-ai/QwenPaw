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


def _block_has_answer_content(block: Any) -> bool:
    """Return whether one block is user-visible answer or tool progress."""
    if isinstance(block, TextBlock):
        return bool(block.text.strip())
    if isinstance(block, ThinkingBlock):
        return False
    if isinstance(block, ToolCallBlock):
        return True
    if isinstance(block, DataBlock):
        return _block_has_meaningful_content(block)
    if isinstance(block, Mapping):
        block_type = block.get("type")
        if block_type == "thinking":
            return False
        if block_type == "text":
            return bool(str(block.get("text", "")).strip())
        if block_type in {"tool_call", "tool_use"}:
            return True
        if block_type == "data":
            return _block_has_meaningful_content(block)
        return bool(block)
    if isinstance(block, str):
        return bool(block.strip())
    return bool(block)


def has_answer_or_tool_progress(content: Any) -> bool:
    """Return whether output contains an answer or a tool call.

    Thinking keeps a stream alive for timeout tracking but is not an answer
    and is safe to discard when a completed turn is retried before any
    answer or tool call has been exposed.
    """
    if isinstance(content, Sequence) and not isinstance(
        content,
        (str, bytes, bytearray),
    ):
        return any(_block_has_answer_content(block) for block in content)
    return _block_has_answer_content(content)


def pre_answer_buffer_weight(content: Any) -> int:
    """Estimate buffered pre-answer text size without serializing payloads."""
    if isinstance(content, Sequence) and not isinstance(
        content,
        (str, bytes, bytearray),
    ):
        return sum(pre_answer_buffer_weight(block) for block in content)
    if isinstance(content, TextBlock):
        return len(content.text.encode("utf-8"))
    if isinstance(content, ThinkingBlock):
        return len(content.thinking.encode("utf-8"))
    if isinstance(content, Mapping):
        if content.get("type") == "text":
            return len(str(content.get("text", "")).encode("utf-8"))
        if content.get("type") == "thinking":
            return len(str(content.get("thinking", "")).encode("utf-8"))
        return 0
    if isinstance(content, str):
        return len(content.encode("utf-8"))
    return 0
