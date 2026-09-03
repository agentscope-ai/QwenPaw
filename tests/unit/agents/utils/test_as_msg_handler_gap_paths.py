# -*- coding: utf-8 -*-
"""Gap-path tests for AsMsgHandler block statistics.

Complements ``test_as_msg_handler.py`` by covering ``stat_message``
branch dispatch (text/thinking/media/tool_call/tool_result), the
tool-result output formatter, and the data-URL aware text counter.
"""
# pylint: disable=protected-access
from __future__ import annotations

import pytest

from qwenpaw.agents.utils.as_msg_handler import AsMsgHandler
from qwenpaw.agents.utils.estimate_token_counter import EstimatedTokenCounter


@pytest.fixture
def handler() -> AsMsgHandler:
    return AsMsgHandler(EstimatedTokenCounter())


def _msg(content):
    """Build a minimal message namespace for stat_message."""
    from types import SimpleNamespace

    return SimpleNamespace(
        name="alice",
        role="assistant",
        content=content,
        timestamp="2026-09-03T10:00:00",
        metadata={"k": "v"},
    )


# ---------------------------------------------------------------------------
# stat_message with string content
# ---------------------------------------------------------------------------


class TestStatMessageString:
    async def test_plain_string_content(self, handler):
        stat = await handler.stat_message(_msg("hello world"))
        assert stat.name == "alice"
        assert stat.role == "assistant"
        assert len(stat.content) == 1
        block = stat.content[0]
        assert block.block_type == "text"
        assert block.text == "hello world"
        assert block.token_count > 0
        assert stat.timestamp == "2026-09-03T10:00:00"
        assert stat.metadata == {"k": "v"}


# ---------------------------------------------------------------------------
# stat_message block dispatch
# ---------------------------------------------------------------------------


class TestStatMessageBlocks:
    async def test_text_block(self, handler):
        stat = await handler.stat_message(
            _msg([{"type": "text", "text": "hi"}]),
        )
        assert stat.content[0].block_type == "text"
        assert stat.content[0].text == "hi"

    async def test_thinking_block(self, handler):
        stat = await handler.stat_message(
            _msg([{"type": "thinking", "thinking": "ponder..."}]),
        )
        assert stat.content[0].block_type == "thinking"
        assert stat.content[0].text == "ponder..."

    async def test_image_block_with_base64_source(self, handler):
        block = {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"},
        }
        stat = await handler.stat_message(_msg([block]))
        out = stat.content[0]
        assert out.block_type == "image"
        assert out.token_count > 0

    async def test_data_block_dispatches_display_type_by_mime(
        self,
        handler,
    ):
        block = {
            "type": "data",
            "source": {
                "type": "base64",
                "media_type": "audio/wav",
                "data": "AAAA",
            },
        }
        stat = await handler.stat_message(_msg([block]))
        assert stat.content[0].block_type == "audio"

    async def test_media_block_with_url_source(self, handler):
        block = {
            "type": "video",
            "source": {"url": "https://example.com/v.mp4"},
        }
        stat = await handler.stat_message(_msg([block]))
        out = stat.content[0]
        assert out.block_type == "video"
        assert out.media_url == "https://example.com/v.mp4"

    async def test_tool_call_block(self, handler):
        block = {
            "type": "tool_call",
            "name": "search",
            "input": {"q": "cats"},
        }
        stat = await handler.stat_message(_msg([block]))
        out = stat.content[0]
        assert out.block_type == "tool_call"
        assert out.tool_name == "search"
        assert "cats" in out.tool_input

    async def test_tool_call_unserializable_input_falls_back(
        self,
        handler,
    ):
        class Weird:
            def __repr__(self):
                return "<weird>"

        block = {
            "type": "tool_call",
            "name": "t",
            "input": Weird(),
        }
        stat = await handler.stat_message(_msg([block]))
        assert stat.content[0].tool_input == "<weird>"

    async def test_tool_result_string_output(self, handler):
        block = {
            "type": "tool_result",
            "name": "search",
            "output": "two cats found",
        }
        stat = await handler.stat_message(_msg([block]))
        out = stat.content[0]
        assert out.block_type == "tool_result"
        assert out.tool_name == "search"

    async def test_tool_result_block_output(self, handler):
        block = {
            "type": "tool_result",
            "name": "capture",
            "output": [
                {"type": "text", "text": "done"},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": "AAAA",
                    },
                },
            ],
        }
        stat = await handler.stat_message(_msg([block]))
        assert stat.content[0].block_type == "tool_result"

    async def test_pydantic_blocks_normalized(self, handler):
        """Blocks exposing model_dump() are normalized to dicts."""

        class FakeBlock:
            def model_dump(self):
                return {"type": "text", "text": "from-pydantic"}

        stat = await handler.stat_message(_msg([FakeBlock()]))
        assert stat.content[0].text == "from-pydantic"

    async def test_unknown_block_type_skipped(self, handler):
        stat = await handler.stat_message(
            _msg([{"type": "mystery", "x": 1}]),
        )
        assert stat.content == []

    async def test_non_dict_block_raises(self, handler):
        # str blocks have no .get(); the handler does not guard this
        # shape (documented current behavior).
        with pytest.raises(AttributeError):
            await handler.stat_message(_msg(["not-a-block"]))


# ---------------------------------------------------------------------------
# _format_tool_result_output
# ---------------------------------------------------------------------------


class TestFormatToolResultOutput:
    async def test_string_output(self, handler):
        text, tokens = await handler._format_tool_result_output("hello")
        assert text == "hello"
        assert tokens > 0

    async def test_text_blocks_joined(self, handler):
        output = [
            {"type": "text", "text": "line1"},
            {"type": "text", "text": "line2"},
        ]
        text, tokens = await handler._format_tool_result_output(output)
        assert text == "line1\nline2"
        assert tokens > 0

    async def test_media_block_appends_placeholder(self, handler):
        output = [
            {
                "type": "image",
                "source": {"url": "https://x/img.png"},
            },
        ]
        text, tokens = await handler._format_tool_result_output(output)
        assert "[image] https://x/img.png" in text
        assert tokens > 0

    async def test_data_block_display_type_from_mime(self, handler):
        # A url source appends the display-type placeholder text; the
        # display type itself is derived from the MIME prefix.
        output = [
            {
                "type": "data",
                "source": {
                    "url": "https://x/clip.mp4",
                    "media_type": "video/mp4",
                },
            },
        ]
        text, _ = await handler._format_tool_result_output(output)
        assert "[video] https://x/clip.mp4" in text

    async def test_invalid_block_skipped(self, handler):
        output = ["garbage", {"no_type": True}]
        text, tokens = await handler._format_tool_result_output(output)
        assert text == ""
        assert tokens == 0

    async def test_unsupported_type_skipped(self, handler):
        output = [{"type": "mystery"}]
        text, tokens = await handler._format_tool_result_output(output)
        assert text == ""
        assert tokens == 0


# ---------------------------------------------------------------------------
# _tokens_from_source / _count_text_with_data_urls
# ---------------------------------------------------------------------------


class TestTokenEstimates:
    async def test_non_dict_source_returns_fallback(self, handler):
        assert await handler._tokens_from_source("junk") == 10

    async def test_empty_url_returns_fallback(self, handler):
        assert await handler._tokens_from_source({"url": ""}) == 10

    async def test_data_url_source_counted_as_media(self, handler):
        url = "data:image/png;base64,AAAA"
        tokens = await handler._tokens_from_source({"url": url})
        assert tokens > 0

    async def test_plain_url_counted_as_text(self, handler):
        tokens = await handler._tokens_from_source(
            {"url": "https://example.com/page"},
        )
        assert tokens > 0

    async def test_count_text_without_data_urls(self, handler):
        tokens = await handler._count_text_with_data_urls("plain text")
        assert tokens > 0

    async def test_count_text_with_embedded_data_url(self, handler):
        text = "before data:image/png;base64,AAAA after"
        tokens = await handler._count_text_with_data_urls(text)
        assert tokens > 0
