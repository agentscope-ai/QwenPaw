# -*- coding: utf-8 -*-
"""Tests for the WeChat quoted-message processing helper.

Covers _process_quoted_ref_msg across all quoted types (text, image,
voice, file, video, unknown) with the media download stubbed, which
previously had no coverage.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.schemas import ContentType


@pytest.fixture
def channel(tmp_path):
    from qwenpaw.app.channels.renderer import ChannelDisplayConfig
    from qwenpaw.app.channels.wechat.channel import WeChatChannel

    async def process(*a, **kw):
        yield SimpleNamespace(object="message", status="completed")

    ch = WeChatChannel(
        process=process,
        enabled=True,
        bot_token="tok",
        bot_prefix="[Bot] ",
        media_dir=str(tmp_path / "media"),
        display_config=ChannelDisplayConfig(
            show_tool_calls=False,
            show_tool_results=False,
        ),
    )
    return ch


def _ref_msg(quoted_item):
    return {"message_item": quoted_item}


class TestProcessQuotedRefMsg:
    async def test_quoted_text_prepended(self, channel):
        text_parts, content_parts = [], []
        ref = _ref_msg({"type": 1, "text_item": {"text": "original"}})
        await channel._process_quoted_ref_msg(
            ref,
            text_parts,
            content_parts,
            client=object(),
        )
        assert text_parts == ["[quoted message: original]"]
        assert content_parts == []

    async def test_quoted_text_empty_ignored(self, channel):
        text_parts, content_parts = [], []
        ref = _ref_msg({"type": 1, "text_item": {"text": "   "}})
        await channel._process_quoted_ref_msg(
            ref,
            text_parts,
            content_parts,
            client=object(),
        )
        assert text_parts == []

    async def test_quoted_image_downloaded(self, channel, monkeypatch):
        channel._download_media = AsyncMock(return_value="/tmp/img.jpg")
        text_parts, content_parts = [], []
        ref = _ref_msg(
            {
                "type": 2,
                "image_item": {
                    "aeskey": "aabb",
                    "media": {"encrypt_query_param": "q=1"},
                },
            },
        )
        await channel._process_quoted_ref_msg(
            ref,
            text_parts,
            content_parts,
            client=object(),
        )
        assert len(content_parts) == 1
        assert content_parts[0].type == ContentType.IMAGE
        assert content_parts[0].image_url == "/tmp/img.jpg"

    async def test_quoted_image_download_failed(self, channel):
        channel._download_media = AsyncMock(return_value=None)
        text_parts, content_parts = [], []
        ref = _ref_msg(
            {
                "type": 2,
                "image_item": {
                    "aeskey": "aabb",
                    "media": {"encrypt_query_param": "q=1"},
                },
            },
        )
        await channel._process_quoted_ref_msg(
            ref,
            text_parts,
            content_parts,
            client=object(),
        )
        assert text_parts == ["[quoted image: download failed]"]

    async def test_quoted_image_no_url(self, channel):
        text_parts, content_parts = [], []
        ref = _ref_msg({"type": 2, "image_item": {"media": {}}})
        await channel._process_quoted_ref_msg(
            ref,
            text_parts,
            content_parts,
            client=object(),
        )
        assert text_parts == ["[quoted image: no url]"]

    async def test_quoted_voice_with_transcription(self, channel):
        text_parts, content_parts = [], []
        ref = _ref_msg(
            {
                "type": 3,
                "voice_item": {"text_item": {"text": "hello"}},
            },
        )
        await channel._process_quoted_ref_msg(
            ref,
            text_parts,
            content_parts,
            client=object(),
        )
        assert text_parts == ["[quoted voice: hello]"]

    async def test_quoted_voice_no_transcription(self, channel):
        text_parts, content_parts = [], []
        ref = _ref_msg({"type": 3, "voice_item": {}})
        await channel._process_quoted_ref_msg(
            ref,
            text_parts,
            content_parts,
            client=object(),
        )
        assert text_parts == ["[quoted voice: no transcription]"]

    async def test_quoted_file_downloaded(self, channel):
        channel._download_media = AsyncMock(return_value="/tmp/doc.pdf")
        text_parts, content_parts = [], []
        ref = _ref_msg(
            {
                "type": 4,
                "file_item": {
                    "file_name": "doc.pdf",
                    "media": {"encrypt_query_param": "q=1", "aes_key": "k"},
                },
            },
        )
        await channel._process_quoted_ref_msg(
            ref,
            text_parts,
            content_parts,
            client=object(),
        )
        assert len(content_parts) == 1
        assert content_parts[0].type == ContentType.FILE

    async def test_quoted_file_no_url(self, channel):
        text_parts, content_parts = [], []
        ref = _ref_msg({"type": 4, "file_item": {"media": {}}})
        await channel._process_quoted_ref_msg(
            ref,
            text_parts,
            content_parts,
            client=object(),
        )
        assert text_parts == ["[quoted file: no url]"]

    async def test_quoted_video_downloaded(self, channel):
        channel._download_media = AsyncMock(return_value="/tmp/v.mp4")
        text_parts, content_parts = [], []
        ref = _ref_msg(
            {
                "type": 5,
                "video_item": {
                    "media": {"encrypt_query_param": "q=1", "aes_key": "k"},
                },
            },
        )
        await channel._process_quoted_ref_msg(
            ref,
            text_parts,
            content_parts,
            client=object(),
        )
        assert len(content_parts) == 1
        assert content_parts[0].type == ContentType.VIDEO

    async def test_empty_ref_msg(self, channel):
        text_parts, content_parts = [], []
        await channel._process_quoted_ref_msg(
            {},
            text_parts,
            content_parts,
            client=object(),
        )
        assert text_parts == []
        assert content_parts == []

    async def test_unknown_type_noted(self, channel):
        text_parts, content_parts = [], []
        ref = _ref_msg({"type": 99})
        await channel._process_quoted_ref_msg(
            ref,
            text_parts,
            content_parts,
            client=object(),
        )
        assert len(text_parts) == 1
