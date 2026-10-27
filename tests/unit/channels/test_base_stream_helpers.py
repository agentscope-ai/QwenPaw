# -*- coding: utf-8 -*-
"""Tests for BaseChannel streaming/tool-output/SSE helpers.

Covers _truncate_stream_tool_chunk, _format_stream_tool_output_body,
_extract_text_from_event, _response_to_text, and
_serialize_event_for_sse headline stripping, which previously had no
coverage.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from qwenpaw.app.channels.console.channel import ConsoleChannel


@pytest.fixture
def channel():
    async def process(*a, **kw):
        yield SimpleNamespace(object="message", status="completed")

    return ConsoleChannel(
        process=process,
        enabled=True,
        bot_prefix="[TEST] ",
    )


# ---------------------------------------------------------------------------
# _truncate_stream_tool_chunk
# ---------------------------------------------------------------------------


class TestTruncateStreamToolChunk:
    def test_short_text_unchanged(self, channel):
        assert channel._truncate_stream_tool_chunk("hello") == "hello"

    def test_whitespace_collapsed(self, channel):
        assert channel._truncate_stream_tool_chunk("a   b\n\nc") == "a b c"

    def test_long_text_truncated(self, channel):
        result = channel._truncate_stream_tool_chunk("x" * 200, limit=10)
        assert result == "x" * 10 + "..."

    def test_none_treated_as_empty(self, channel):
        assert channel._truncate_stream_tool_chunk(None) == ""


# ---------------------------------------------------------------------------
# _format_stream_tool_output_body
# ---------------------------------------------------------------------------


class TestFormatStreamToolOutputBody:
    def test_non_dict_data_returns_none(self, channel):
        event = SimpleNamespace(data="not-a-dict")
        assert channel._format_stream_tool_output_body(event) is None

    def test_output_not_list_returns_none(self, channel):
        event = SimpleNamespace(data={"output": "plain"})
        assert channel._format_stream_tool_output_body(event) is None

    def test_json_string_output_parsed(self, channel):
        output = [{"type": "text", "text": "result"}]
        event = SimpleNamespace(
            data={"output": json.dumps(output), "name": "search"},
        )
        result = channel._format_stream_tool_output_body(event)
        assert "search" in result
        assert "result" in result

    def test_invalid_json_output_returns_none(self, channel):
        event = SimpleNamespace(data={"output": "{broken"})
        assert channel._format_stream_tool_output_body(event) is None

    def test_text_and_thinking_blocks(self, channel):
        output = [
            {"type": "text", "text": "answer"},
            {"type": "thinking", "thinking": "reasoning"},
        ]
        event = SimpleNamespace(data={"output": output, "name": "tool"})
        result = channel._format_stream_tool_output_body(event)
        assert "answer" in result
        assert "reasoning" in result

    def test_empty_blocks_returns_none(self, channel):
        output = [{"type": "text", "text": "   "}]
        event = SimpleNamespace(data={"output": output})
        assert channel._format_stream_tool_output_body(event) is None

    def test_duplicate_chunks_deduplicated(self, channel):
        output = [
            {"type": "text", "text": "same"},
            {"type": "text", "text": "same"},
        ]
        event = SimpleNamespace(data={"output": output})
        result = channel._format_stream_tool_output_body(event)
        assert result.count("same") == 1

    def test_non_dict_blocks_skipped(self, channel):
        output = ["not-a-dict", {"type": "text", "text": "ok"}]
        event = SimpleNamespace(data={"output": output})
        result = channel._format_stream_tool_output_body(event)
        assert "ok" in result

    def test_default_tool_name(self, channel):
        output = [{"type": "text", "text": "x"}]
        event = SimpleNamespace(data={"output": output})
        result = channel._format_stream_tool_output_body(event)
        assert "tool" in result


# ---------------------------------------------------------------------------
# _extract_text_from_event
# ---------------------------------------------------------------------------


class TestExtractTextFromEvent:
    def test_no_content_returns_empty(self):
        assert (
            ConsoleChannel._extract_text_from_event(
                SimpleNamespace(content=None),
            )
            == ""
        )

    def test_content_not_list_returns_empty(self):
        assert (
            ConsoleChannel._extract_text_from_event(
                SimpleNamespace(content="str"),
            )
            == ""
        )

    def test_texts_concatenated(self):
        event = SimpleNamespace(
            content=[
                SimpleNamespace(text="a"),
                SimpleNamespace(text="b"),
            ],
        )
        assert ConsoleChannel._extract_text_from_event(event) == "ab"

    def test_items_without_text_skipped(self):
        event = SimpleNamespace(
            content=[
                SimpleNamespace(text="a"),
                SimpleNamespace(),
            ],
        )
        assert ConsoleChannel._extract_text_from_event(event) == "a"


# ---------------------------------------------------------------------------
# _response_to_text
# ---------------------------------------------------------------------------


class TestResponseToText:
    def _message(self, text):
        from qwenpaw.schemas import ContentType, MessageType, TextContent

        return SimpleNamespace(
            type=MessageType.MESSAGE,
            content=[TextContent(type=ContentType.TEXT, text=text)],
        )

    def test_empty_output_returns_empty(self, channel):
        assert channel._response_to_text(SimpleNamespace(output=[])) == ""

    def test_last_message_text(self, channel):
        response = SimpleNamespace(output=[self._message("final answer")])
        assert channel._response_to_text(response) == "final answer"

    def test_skips_trailing_non_message(self, channel):
        from qwenpaw.schemas import MessageType

        non_msg = SimpleNamespace(type=MessageType.REASONING, content=[])
        response = SimpleNamespace(
            output=[self._message("answer"), non_msg],
        )
        assert channel._response_to_text(response) == "answer"

    def test_no_message_returns_empty(self, channel):
        from qwenpaw.schemas import MessageType

        response = SimpleNamespace(
            output=[SimpleNamespace(type=MessageType.REASONING, content=[])],
        )
        assert channel._response_to_text(response) == ""

    def test_message_with_empty_content_skipped(self, channel):
        from qwenpaw.schemas import MessageType

        empty_msg = SimpleNamespace(type=MessageType.MESSAGE, content=[])
        response = SimpleNamespace(
            output=[self._message("real"), empty_msg],
        )
        assert channel._response_to_text(response) == "real"


# ---------------------------------------------------------------------------
# _serialize_event_for_sse
# ---------------------------------------------------------------------------


class TestSerializeEventForSse:
    def test_model_dump_json_used(self, channel):
        event = SimpleNamespace(
            model_dump_json=lambda: '{"object":"message"}',
        )
        result = channel._serialize_event_for_sse(event)
        assert result == '{"object":"message"}'

    def test_json_fallback(self, channel):
        class OldEvent:
            def json(self):
                return '{"old":true}'

        result = channel._serialize_event_for_sse(OldEvent())
        assert result == '{"old":true}'

    def test_str_fallback(self, channel):
        result = channel._serialize_event_for_sse("plain text")
        assert "plain text" in result

    def test_headline_stripped_when_tracked(self, channel):
        """A tracked delta content event containing a fence marker has the
        headline region removed from the serialized output."""
        body = {
            "object": "content",
            "delta": True,
            "text": "before ⟦tag⟧ after",
        }
        event = SimpleNamespace(
            object="content",
            delta=True,
            model_dump_json=lambda: json.dumps(body, ensure_ascii=True),
        )
        states = {"k": {}}
        result = channel._serialize_event_for_sse(event, states)
        assert isinstance(result, str)

    def test_no_fence_marker_untouched(self, channel):
        body = {"object": "content", "delta": True, "text": "no marker"}
        event = SimpleNamespace(
            object="content",
            delta=True,
            model_dump_json=lambda: json.dumps(body, ensure_ascii=True),
        )
        result = channel._serialize_event_for_sse(event, {"k": {}})
        assert "no marker" in result
