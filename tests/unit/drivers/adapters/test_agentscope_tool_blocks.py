# -*- coding: utf-8 -*-
"""Unit tests for _blocks_from_value in the AgentScope tool adapter.

Checks that an MCP-style call result yields a single, non-duplicated
tool-result block — specifically that ``structuredContent`` is preferred as
the canonical form instead of being written alongside a redundant
``content`` rendering (see #6958).
"""

import json

from qwenpaw.drivers.adapters.agentscope_tool import _blocks_from_value


class _TextItem:
    """Minimal stand-in for an MCP text content item."""

    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _CallResult:
    """Minimal stand-in for an MCP ``CallToolResult``."""

    def __init__(
        self,
        content=None,
        structured=None,
        is_error: bool = False,
    ) -> None:
        self.content = content
        self.structuredContent = structured
        self.isError = is_error


def test_structured_content_deduped_when_content_present() -> None:
    """No duplicate when both content and structuredContent exist."""
    structured = {"name": "weather", "temp": 23}
    result = _CallResult(
        content=[_TextItem(json.dumps(structured, ensure_ascii=False))],
        structured=structured,
    )

    blocks = _blocks_from_value(result)

    assert len(blocks) == 1
    payload = json.loads(blocks[0].text)
    assert payload == structured


def test_content_blocks_used_when_structured_absent() -> None:
    """With no structuredContent, the content blocks are kept as-is."""
    result = _CallResult(
        content=[_TextItem("plain text answer")],
        structured=None,
    )

    blocks = _blocks_from_value(result)

    assert len(blocks) == 1
    assert blocks[0].text == "plain text answer"


def test_empty_content_falls_back_to_empty_block() -> None:
    """An empty MCP result yields a single empty block rather than crashing."""
    result = _CallResult(content=[], structured=None, is_error=False)

    assert len(_blocks_from_value(result)) == 1


def test_plain_value_uses_stringify() -> None:
    """Non-MCP values are stringified into a single block as before."""
    assert _blocks_from_value({"a": 1})[0].text.lstrip().startswith("{")
