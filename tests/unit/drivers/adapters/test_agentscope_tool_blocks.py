# -*- coding: utf-8 -*-
"""Unit tests for _blocks_from_value in the AgentScope tool adapter.

Guards the tool-result rendering (see #6958): ``content`` blocks are the
safe side and must never be dropped, while ``structuredContent`` is only
appended when it is not already represented in ``content`` (so the common
JSON-payload duplication is removed without losing image / audio / resource
blocks that ``structuredContent`` cannot express).
"""

import json

from qwenpaw.drivers.adapters.agentscope_tool import _blocks_from_value


class _TextItem:
    """Minimal stand-in for an MCP text content item."""

    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _ImageItem:
    """Minimal stand-in for an MCP image content item (data + mimeType)."""

    def __init__(self) -> None:
        self.data = "iVBORw0KGgo="
        self.mimeType = "image/png"


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


def test_structured_deduped_when_content_has_same_json() -> None:
    """dict / TypedDict payload: content JSON == structured -> one block."""
    structured = {"name": "weather", "temp": 23}
    result = _CallResult(
        content=[_TextItem(json.dumps(structured, ensure_ascii=False))],
        structured=structured,
    )

    blocks = _blocks_from_value(result)

    assert len(blocks) == 1
    assert json.loads(blocks[0].text) == structured


def test_wrap_output_str_result_not_wrapped() -> None:
    """FastMCP wrap_output: structured {\"result\": text} keeps raw text."""
    result = _CallResult(
        content=[_TextItem("plain text answer")],
        structured={"result": "plain text answer"},
    )

    blocks = _blocks_from_value(result)

    assert len(blocks) == 1
    assert blocks[0].text == "plain text answer"


def test_image_block_survives_when_structured_present() -> None:
    """A content image block survives even when structuredContent is set."""
    result = _CallResult(
        content=[_ImageItem()],
        structured={"points": 42},
    )

    blocks = _blocks_from_value(result)

    assert len(blocks) == 2
    # the image block is kept (DataBlock carries no text)
    assert getattr(blocks[0], "text", None) is None
    # structured content appended afterwards when not covered
    assert json.loads(blocks[1].text) == {"points": 42}


def test_structured_appended_when_not_covered() -> None:
    """A summary in content does not suppress a distinct structured payload."""
    result = _CallResult(
        content=[_TextItem("summarized")],
        structured={"full": [1, 2, 3]},
    )

    blocks = _blocks_from_value(result)

    assert len(blocks) == 2
    assert blocks[0].text == "summarized"
    assert json.loads(blocks[1].text) == {"full": [1, 2, 3]}


def test_content_blocks_used_when_structured_absent() -> None:
    """With no structuredContent, the content blocks are kept unchanged."""
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
