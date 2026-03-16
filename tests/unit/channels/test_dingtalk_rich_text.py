# -*- coding: utf-8 -*-
"""Tests for DingTalk rich text parsing - empty text blocks must be skipped."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from copaw.app.channels.dingtalk.handler import DingTalkChannelHandler


def _make_handler() -> DingTalkChannelHandler:
    """Create a handler with stubbed dependencies."""
    import asyncio

    loop = asyncio.new_event_loop()
    handler = DingTalkChannelHandler(
        main_loop=loop,
        enqueue_callback=None,
        bot_prefix="",
        download_url_fetcher=MagicMock(),
    )
    return handler


def _make_incoming(rich_text_items: list) -> MagicMock:
    """Build a mock incoming_message with richText content."""
    msg = MagicMock()
    msg.robot_code = "test_robot"
    msg.to_dict.return_value = {"content": {"richText": rich_text_items}}
    return msg


class TestParseRichContent:
    """Verify _parse_rich_content filters empty text blocks."""

    def test_empty_text_items_are_skipped(self) -> None:
        handler = _make_handler()
        items = [
            {"text": ""},
            {"text": "   "},
            {"content": ""},
            {"content": None},
        ]
        result = handler._parse_rich_content(_make_incoming(items))
        text_parts = [p for p in result if hasattr(p, "text")]
        assert (
            len(text_parts) == 0
        ), f"Expected no TextContent blocks, got {text_parts}"

    def test_valid_text_items_are_kept(self) -> None:
        handler = _make_handler()
        items = [
            {"text": "hello"},
            {"text": "  world  "},
        ]
        result = handler._parse_rich_content(_make_incoming(items))
        text_parts = [p for p in result if hasattr(p, "text")]
        assert len(text_parts) == 2
        assert text_parts[0].text == "hello"
        assert text_parts[1].text == "world"

    def test_mixed_empty_and_valid(self) -> None:
        handler = _make_handler()
        items = [
            {"text": ""},
            {"text": "keep this"},
            {"text": "   "},
            {"content": "also keep"},
        ]
        result = handler._parse_rich_content(_make_incoming(items))
        text_parts = [p for p in result if hasattr(p, "text")]
        assert len(text_parts) == 2
        assert text_parts[0].text == "keep this"
        assert text_parts[1].text == "also keep"
