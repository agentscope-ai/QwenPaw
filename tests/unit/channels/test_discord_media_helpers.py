# -*- coding: utf-8 -*-
"""Tests for Discord attachment classification and stream display helpers.

Covers _classify_attachment (content-type / filename-MIME priority) and
_build_stream_display_text (bot_prefix / reasoning emoji), which were
previously untested.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.app.channels.discord_.channel import DiscordChannel


@pytest.fixture
def channel():
    async def process(*a, **kw):
        yield SimpleNamespace(object="message", status="completed")

    return DiscordChannel(
        process=process,
        enabled=False,
        token="tok",
        http_proxy="",
        http_proxy_auth="",
        bot_prefix="[BOT] ",
    )


def _attachment(content_type="", filename=""):
    return SimpleNamespace(content_type=content_type, filename=filename)


# ---------------------------------------------------------------------------
# _classify_attachment
# ---------------------------------------------------------------------------


class TestClassifyAttachment:
    def test_content_type_image(self):
        assert (
            DiscordChannel._classify_attachment(
                _attachment(content_type="image/png"),
            )
            == "image"
        )

    def test_content_type_video(self):
        assert (
            DiscordChannel._classify_attachment(
                _attachment(content_type="video/mp4"),
            )
            == "video"
        )

    def test_content_type_audio(self):
        assert (
            DiscordChannel._classify_attachment(
                _attachment(content_type="audio/mpeg"),
            )
            == "audio"
        )

    def test_filename_guessed_image(self):
        assert (
            DiscordChannel._classify_attachment(_attachment(filename="a.png"))
            == "image"
        )

    def test_filename_guessed_video(self):
        assert (
            DiscordChannel._classify_attachment(_attachment(filename="v.mp4"))
            == "video"
        )

    def test_content_type_takes_priority_over_filename(self):
        assert (
            DiscordChannel._classify_attachment(
                _attachment(content_type="application/pdf", filename="x.png"),
            )
            == "file"
        )

    def test_unknown_falls_to_file(self):
        assert (
            DiscordChannel._classify_attachment(
                _attachment(content_type="application/pdf", filename="d.pdf"),
            )
            == "file"
        )

    def test_empty_attachment_is_file(self):
        assert DiscordChannel._classify_attachment(_attachment()) == "file"


# ---------------------------------------------------------------------------
# _build_stream_display_text
# ---------------------------------------------------------------------------


class TestBuildStreamDisplayText:
    def test_text_with_meta_prefix(self, channel):
        result = channel._build_stream_display_text(
            "message",
            "hello",
            {"bot_prefix": "[META] "},
        )
        assert result == "[META]   hello"

    def test_text_with_channel_prefix(self, channel):
        result = channel._build_stream_display_text(
            "message",
            "hello",
            {},
        )
        assert result == "[BOT]   hello"

    def test_reasoning_with_prefix_and_emoji(self, channel):
        result = channel._build_stream_display_text(
            "reasoning",
            "thinking...",
            {},
        )
        assert result == "[BOT]   💭 thinking..."

    def test_reasoning_without_prefix(self, channel):
        channel.bot_prefix = ""
        result = channel._build_stream_display_text(
            "reasoning",
            "thinking...",
            {},
        )
        assert result == "💭 thinking..."

    def test_no_prefix_no_text_returns_empty(self, channel):
        channel.bot_prefix = ""
        assert channel._build_stream_display_text("message", "", {}) == ""

    def test_empty_text_with_prefix_returns_empty(self, channel):
        assert channel._build_stream_display_text("message", "", {}) == ""
