# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for OneBot v11 channel."""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock
import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from pydantic import ValidationError
from qwenpaw.config.config import OneBotConfig
from qwenpaw.schemas import (
    ContentType,
    TextContent,
)

from qwenpaw.app.channels.onebot import channel as onebot_channel_module
from qwenpaw.app.channels.onebot.channel import (
    OneBotChannel,
    _normalize_media_ref_sync,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_channel(**overrides: Any) -> OneBotChannel:
    """Create an OneBotChannel with dummy process handler."""

    async def _noop_process(_request):
        yield  # pragma: no cover

    defaults = {
        "process": _noop_process,
        "enabled": True,
        "ws_host": "127.0.0.1",
        "ws_port": 6199,
        "access_token": "",
        "bot_prefix": "",
    }
    defaults.update(overrides)
    return OneBotChannel(**defaults)


def test_media_base64_config():
    async def _noop_process(_request):
        yield  # pragma: no cover

    config = OneBotConfig(
        enabled=True,
        media_base64=True,
        media_base64_max_mb=3,
    )
    ch = OneBotChannel.from_config(
        _noop_process,
        config,
    )

    assert OneBotConfig().model_dump()["media_base64_max_mb"] == 10
    assert config.model_dump()["media_base64_max_mb"] == 3
    assert ch._media_base64 is True
    assert ch._media_base64_max_bytes == 3_000_000
    with pytest.raises(ValidationError):
        OneBotConfig(media_base64_max_mb=0)


def _make_message_event(
    message_type: str = "private",
    user_id: int = 12345,
    group_id: int = 0,
    message_id: int = 1001,
    segments: list | None = None,
    sender: dict | None = None,
) -> dict:
    """Build a minimal OneBot v11 message event."""
    if segments is None:
        segments = [{"type": "text", "data": {"text": "hello"}}]
    if sender is None:
        sender = {"nickname": "TestUser", "card": ""}
    event = {
        "post_type": "message",
        "message_type": message_type,
        "user_id": user_id,
        "message_id": message_id,
        "message": segments,
        "sender": sender,
    }
    if group_id:
        event["group_id"] = group_id
    return event


# ===================================================================
# Message segment parsing
# ===================================================================


class TestParseMessageSegments:
    def test_text_only(self):
        ch = _make_channel()
        parts, mentioned = ch._parse_message_segments(
            [{"type": "text", "data": {"text": "hello world"}}],
        )
        assert len(parts) == 1
        assert parts[0].type == ContentType.TEXT
        assert parts[0].text == "hello world"
        assert mentioned is False

    def test_empty_text_skipped(self):
        ch = _make_channel()
        parts, _ = ch._parse_message_segments(
            [{"type": "text", "data": {"text": "  "}}],
        )
        assert len(parts) == 0

    def test_image_segment(self):
        ch = _make_channel()
        parts, _ = ch._parse_message_segments(
            [
                {
                    "type": "image",
                    "data": {"url": "https://img.example.com/1.jpg"},
                },
            ],
        )
        assert len(parts) == 1
        assert parts[0].type == ContentType.IMAGE
        assert parts[0].image_url == "https://img.example.com/1.jpg"

    def test_image_file_fallback(self):
        ch = _make_channel()
        parts, _ = ch._parse_message_segments(
            [{"type": "image", "data": {"file": "file:///tmp/1.jpg"}}],
        )
        assert len(parts) == 1
        assert parts[0].image_url == "file:///tmp/1.jpg"

    def test_record_segment(self):
        ch = _make_channel()
        parts, _ = ch._parse_message_segments(
            [
                {
                    "type": "record",
                    "data": {"url": "https://audio.example.com/a.mp3"},
                },
            ],
        )
        assert len(parts) == 1
        assert parts[0].type == ContentType.AUDIO

    def test_video_segment(self):
        ch = _make_channel()
        parts, _ = ch._parse_message_segments(
            [
                {
                    "type": "video",
                    "data": {"url": "https://video.example.com/v.mp4"},
                },
            ],
        )
        assert len(parts) == 1
        assert parts[0].type == ContentType.VIDEO

    def test_file_segment(self):
        ch = _make_channel()
        parts, _ = ch._parse_message_segments(
            [
                {
                    "type": "file",
                    "data": {
                        "url": "https://files.example.com/doc.pdf",
                        "name": "doc.pdf",
                    },
                },
            ],
        )
        assert len(parts) == 1
        assert parts[0].type == ContentType.FILE

    def test_at_bot_detected(self):
        ch = _make_channel()
        ch._self_id = 99999
        parts, mentioned = ch._parse_message_segments(
            [
                {"type": "at", "data": {"qq": "99999"}},
                {"type": "text", "data": {"text": "hello bot"}},
            ],
        )
        assert mentioned is True
        assert len(parts) == 1
        assert parts[0].text == "hello bot"

    def test_at_other_user_not_mentioned(self):
        ch = _make_channel()
        ch._self_id = 99999
        _, mentioned = ch._parse_message_segments(
            [
                {"type": "at", "data": {"qq": "11111"}},
                {"type": "text", "data": {"text": "hello"}},
            ],
        )
        assert mentioned is False

    def test_mixed_segments(self):
        ch = _make_channel()
        parts, _ = ch._parse_message_segments(
            [
                {"type": "text", "data": {"text": "look at this"}},
                {
                    "type": "image",
                    "data": {"url": "https://img.example.com/pic.png"},
                },
                {"type": "reply", "data": {"id": "123"}},
                {"type": "face", "data": {"id": "178"}},
            ],
        )
        assert len(parts) == 2
        assert parts[0].type == ContentType.TEXT
        assert parts[1].type == ContentType.IMAGE

    def test_unknown_segment_ignored(self):
        ch = _make_channel()
        parts, _ = ch._parse_message_segments(
            [{"type": "unknown_type", "data": {}}],
        )
        assert len(parts) == 0

    def test_normalize_cq_code_message(self):
        segments = OneBotChannel._normalize_onebot_segments(
            "hello [CQ:image,file=pic.jpg,"
            "url=https://img.example.com/pic.jpg]",
        )

        assert segments == [
            {"type": "text", "data": {"text": "hello"}},
            {
                "type": "image",
                "data": {
                    "file": "pic.jpg",
                    "url": "https://img.example.com/pic.jpg",
                },
            },
        ]

    def test_normalize_cq_code_decodes_escaped_parameters(self):
        segments = OneBotChannel._normalize_onebot_segments(
            "[CQ:image,file=a&#44;b&#91;c&#93;.jpg,"
            "title=&lt;literal&gt;,"
            "url=https://cdn.example/a?x=1&#38;y=2]",
        )

        assert segments == [
            {
                "type": "image",
                "data": {
                    "file": "a,b[c].jpg",
                    "title": "&lt;literal&gt;",
                    "url": "https://cdn.example/a?x=1&y=2",
                },
            },
        ]

    def test_message_preview_bounds_fields_before_serializing(
        self,
        monkeypatch,
    ):
        captured: list = []
        real_dumps = onebot_channel_module.json.dumps

        def capture_dumps(value, *args, **kwargs):
            captured.append(value)
            return real_dumps(value, *args, **kwargs)

        monkeypatch.setattr(onebot_channel_module.json, "dumps", capture_dumps)
        preview = OneBotChannel._message_preview(
            [
                {
                    "type": "image",
                    "data": {
                        "url": "x" * 1_000_000,
                        "nested": {"payload": "y" * 1_000_000},
                    },
                },
            ],
        )

        assert len(preview) <= 200
        assert len(captured[0][0]["data"]["url"]) == 80
        assert captured[0][0]["data"]["nested"] == "<dict>"


# ===================================================================
# Message event handling
# ===================================================================


class TestHandleMessageEvent:
    async def test_private_message_enqueues(self):
        ch = _make_channel()
        enqueued: list = []
        ch._enqueue = enqueued.append

        event = _make_message_event(message_type="private", user_id=12345)
        await ch._handle_message_event(event)

        assert len(enqueued) == 1
        req = enqueued[0]
        assert req.session_id == "onebot:12345"
        assert req.channel_meta["message_type"] == "private"
        assert req.channel_meta["sender_id"] == "12345"

    async def test_group_message_enqueues(self):
        ch = _make_channel()
        enqueued: list = []
        ch._enqueue = enqueued.append

        event = _make_message_event(
            message_type="group",
            user_id=12345,
            group_id=67890,
        )
        await ch._handle_message_event(event)

        assert len(enqueued) == 1
        req = enqueued[0]
        assert req.session_id == "onebot:67890:12345"
        assert req.channel_meta["is_group"] is True
        assert req.channel_meta["group_id"] == "67890"

    async def test_empty_message_ignored(self):
        ch = _make_channel()
        enqueued: list = []
        ch._enqueue = enqueued.append

        event = _make_message_event(segments=[])
        await ch._handle_message_event(event)
        assert len(enqueued) == 0

    async def test_string_message_wrapped(self):
        """OneBot implementations may send message as plain string."""
        ch = _make_channel()
        enqueued: list = []
        ch._enqueue = enqueued.append

        event = _make_message_event()
        event["message"] = "plain text message"
        await ch._handle_message_event(event)

        assert len(enqueued) == 1

    async def test_access_control_dm_flag(self):
        ch = _make_channel(
            access_control_dm=True,
        )
        # access_control_dm=True should enable access control
        assert ch.access_control_dm is True
        assert ch.access_control_enabled is True

    async def test_allowlist_allows_permitted_user(self):
        ch = _make_channel(
            dm_policy="allowlist",
            allow_from=["12345"],
        )
        enqueued: list = []
        ch._enqueue = enqueued.append

        event = _make_message_event(user_id=12345)
        await ch._handle_message_event(event)
        assert len(enqueued) == 1

    async def test_require_mention_blocks_without_at(self):
        ch = _make_channel(require_mention=True)
        ch._self_id = 99999
        enqueued: list = []
        ch._enqueue = enqueued.append

        event = _make_message_event(
            message_type="group",
            group_id=67890,
            segments=[{"type": "text", "data": {"text": "hello"}}],
        )
        await ch._handle_message_event(event)
        assert len(enqueued) == 0

    async def test_require_mention_allows_with_at(self):
        ch = _make_channel(require_mention=True)
        ch._self_id = 99999
        enqueued: list = []
        ch._enqueue = enqueued.append

        event = _make_message_event(
            message_type="group",
            group_id=67890,
            segments=[
                {"type": "at", "data": {"qq": "99999"}},
                {"type": "text", "data": {"text": "hello"}},
            ],
        )
        await ch._handle_message_event(event)
        assert len(enqueued) == 1

    async def test_require_mention_allows_with_event_self_id(self):
        ch = _make_channel(require_mention=True)
        enqueued: list = []
        ch._enqueue = enqueued.append

        event = _make_message_event(
            message_type="group",
            group_id=67890,
            segments=[
                {"type": "at", "data": {"qq": "99999"}},
                {"type": "text", "data": {"text": "hello"}},
            ],
        )
        event["self_id"] = 99999
        await ch._handle_message_event(event)

        assert len(enqueued) == 1
        assert ch._self_id == 99999

    async def test_quoted_text_is_fetched_after_mention(self):
        ch = _make_channel(require_mention=True)
        ch._self_id = 99999
        ch._call_api = AsyncMock(
            return_value={
                "data": {
                    "message": [
                        {"type": "text", "data": {"text": "quoted text"}},
                    ],
                },
            },
        )
        enqueued: list = []
        ch._enqueue = enqueued.append

        event = _make_message_event(
            message_type="group",
            group_id=67890,
            segments=[
                {"type": "reply", "data": {"id": "321"}},
                {"type": "at", "data": {"qq": "99999"}},
                {"type": "text", "data": {"text": "please answer"}},
            ],
        )
        await ch._handle_message_event(event)

        ch._call_api.assert_awaited_once_with("get_msg", {"message_id": 321})
        assert len(enqueued) == 1
        content = enqueued[0].input[0].content
        assert len(content) == 1
        assert content[0].text == (
            "[Quoted message]\nquoted text\n\n"
            "[Current message]\nplease answer"
        )

    async def test_quoted_cq_image_is_marked_as_quoted_content(self):
        ch = _make_channel(require_mention=True)
        ch._self_id = 99999
        ch._call_api = AsyncMock(
            return_value={
                "data": {
                    "message": (
                        "[CQ:image,file=pic.jpg,"
                        "url=https://img.example.com/pic.jpg]"
                    ),
                },
            },
        )
        enqueued: list = []
        ch._enqueue = enqueued.append

        event = _make_message_event(
            message_type="group",
            group_id=67890,
            segments=[
                {"type": "reply", "data": {"id": "321"}},
                {"type": "at", "data": {"qq": "99999"}},
                {"type": "text", "data": {"text": "describe it"}},
            ],
        )
        await ch._handle_message_event(event)

        content = enqueued[0].input[0].content
        assert content[0].text == "[Quoted message]"
        assert content[1].text == "[Quoted image message]"
        assert content[2].type == ContentType.IMAGE
        assert content[2].image_url == "https://img.example.com/pic.jpg"
        assert content[3].text == "[Current message]"
        assert content[4].text == "describe it"

    async def test_quoted_raw_message_is_used_when_message_is_text(self):
        ch = _make_channel(require_mention=True)
        ch._self_id = 99999
        ch._call_api = AsyncMock(
            return_value={
                "data": {
                    "message": "[图片]",
                    "raw_message": (
                        "[CQ:image,file=pic.jpg,"
                        "url=https://img.example.com/pic.jpg]"
                    ),
                },
            },
        )
        enqueued: list = []
        ch._enqueue = enqueued.append

        event = _make_message_event(
            message_type="group",
            group_id=67890,
            segments=[
                {"type": "reply", "data": {"id": "321"}},
                {"type": "at", "data": {"qq": "99999"}},
                {"type": "text", "data": {"text": "describe it"}},
            ],
        )
        await ch._handle_message_event(event)

        content = enqueued[0].input[0].content
        assert content[0].text == "[Quoted message]"
        assert content[1].text == "[Quoted image message]"
        assert content[2].type == ContentType.IMAGE
        assert content[2].image_url == "https://img.example.com/pic.jpg"
        assert content[3].text == "[Current message]"
        assert content[4].text == "describe it"

    async def test_quoted_record_is_marked_as_voice_content(self):
        ch = _make_channel(require_mention=True)
        ch._self_id = 99999
        ch._call_api = AsyncMock(
            return_value={
                "data": {
                    "message": [
                        {
                            "type": "record",
                            "data": {
                                "file": "voice.amr",
                                "url": (
                                    "https://qq.example/" "download?file=voice"
                                ),
                            },
                        },
                    ],
                },
            },
        )
        enqueued: list = []
        ch._enqueue = enqueued.append

        event = _make_message_event(
            message_type="group",
            group_id=67890,
            segments=[
                {"type": "reply", "data": {"id": "321"}},
                {"type": "at", "data": {"qq": "99999"}},
                {"type": "text", "data": {"text": "what is it"}},
            ],
        )
        await ch._handle_message_event(event)

        content = enqueued[0].input[0].content
        assert content[1].text == "[Quoted voice message]"
        assert content[2].type == ContentType.AUDIO
        assert content[2].data == ("https://qq.example/download?file=voice")
        assert content[3].text == "[Current message]"
        assert content[4].text == "what is it"

    async def test_quoted_file_uses_existing_file_url_resolution(self):
        ch = _make_channel(require_mention=True)
        ch._self_id = 99999
        ch._call_api = AsyncMock(
            side_effect=[
                {
                    "data": {
                        "message": [
                            {
                                "type": "file",
                                "data": {
                                    "file": "doc.pdf",
                                    "file_id": "quoted-file-id",
                                    "name": "doc.pdf",
                                },
                            },
                        ],
                    },
                },
                {"data": {"url": "https://files.example.com/doc.pdf"}},
            ],
        )
        enqueued: list = []
        ch._enqueue = enqueued.append

        event = _make_message_event(
            message_type="group",
            group_id=67890,
            segments=[
                {"type": "reply", "data": {"id": "321"}},
                {"type": "at", "data": {"qq": "99999"}},
            ],
        )
        await ch._handle_message_event(event)

        assert ch._call_api.await_args_list[0].args == (
            "get_msg",
            {"message_id": 321},
        )
        assert ch._call_api.await_args_list[1].args == (
            "get_group_file_url",
            {"group_id": 67890, "file_id": "quoted-file-id"},
        )
        assert len(enqueued) == 1
        assert (
            enqueued[0].input[0].content[2].file_url
            == "https://files.example.com/doc.pdf"
        )
        assert enqueued[0].input[0].content[1].text == (
            "[Quoted file message: doc.pdf]"
        )

    async def test_quoted_and_current_files_keep_their_own_file_ids(self):
        ch = _make_channel(require_mention=True)
        ch._self_id = 99999
        ch._call_api = AsyncMock(
            side_effect=[
                {
                    "data": {
                        "message": [
                            {
                                "type": "file",
                                "data": {
                                    "file": "quoted.pdf",
                                    "file_id": "quoted-file-id",
                                    "name": "quoted.pdf",
                                },
                            },
                        ],
                    },
                },
                {"data": {"url": "https://files.example/quoted.pdf"}},
                {"data": {"url": "https://files.example/current.pdf"}},
            ],
        )
        enqueued: list = []
        ch._enqueue = enqueued.append

        event = _make_message_event(
            message_type="group",
            group_id=67890,
            segments=[
                {"type": "reply", "data": {"id": "321"}},
                {"type": "at", "data": {"qq": "99999"}},
                {
                    "type": "file",
                    "data": {
                        "file": "current.pdf",
                        "file_id": "current-file-id",
                        "name": "current.pdf",
                    },
                },
            ],
        )
        await ch._handle_message_event(event)

        assert ch._call_api.await_args_list[1].args == (
            "get_group_file_url",
            {"group_id": 67890, "file_id": "quoted-file-id"},
        )
        assert ch._call_api.await_args_list[2].args == (
            "get_group_file_url",
            {"group_id": 67890, "file_id": "current-file-id"},
        )
        content = enqueued[0].input[0].content
        assert content[2].file_url == "https://files.example/quoted.pdf"
        assert content[4].file_url == "https://files.example/current.pdf"

    async def test_unmentioned_reply_does_not_call_get_msg(self):
        ch = _make_channel(require_mention=True)
        ch._self_id = 99999
        ch._call_api = AsyncMock()
        enqueued: list = []
        ch._enqueue = enqueued.append

        event = _make_message_event(
            message_type="group",
            group_id=67890,
            segments=[{"type": "reply", "data": {"id": "321"}}],
        )
        await ch._handle_message_event(event)

        ch._call_api.assert_not_awaited()
        assert not enqueued


# ===================================================================
# Session ID resolution
# ===================================================================


class TestResolveSessionId:
    def test_private_session(self):
        ch = _make_channel()
        sid = ch.resolve_session_id("12345", {"is_group": False})
        assert sid == "onebot:12345"

    def test_group_per_user(self):
        ch = _make_channel(share_session_in_group=False)
        sid = ch.resolve_session_id(
            "12345",
            {"is_group": True, "group_id": "67890"},
        )
        assert sid == "onebot:67890:12345"

    def test_group_shared(self):
        ch = _make_channel(share_session_in_group=True)
        sid = ch.resolve_session_id(
            "12345",
            {"is_group": True, "group_id": "67890"},
        )
        assert sid == "onebot:g:67890"


# ===================================================================
# get_to_handle_from_request
# ===================================================================


class TestGetToHandle:
    def test_group_message(self):
        ch = _make_channel()
        req = MagicMock()
        req.channel_meta = {"is_group": True, "group_id": "67890"}
        assert ch.get_to_handle_from_request(req) == "group:67890"

    def test_private_message(self):
        ch = _make_channel()
        req = MagicMock()
        req.channel_meta = {"is_group": False, "sender_id": "12345"}
        assert ch.get_to_handle_from_request(req) == "12345"


# ===================================================================
# Send methods
# ===================================================================


class TestSend:
    async def test_disabled_channel_noop(self):
        ch = _make_channel(enabled=False)
        ch._call_api = AsyncMock()
        await ch.send("12345", "hello")
        ch._call_api.assert_not_called()

    async def test_empty_text_noop(self):
        ch = _make_channel()
        ch._call_api = AsyncMock()
        await ch.send("12345", "   ")
        ch._call_api.assert_not_called()

    async def test_private_message_send(self):
        ch = _make_channel()
        ch._call_api = AsyncMock(return_value={"retcode": 0})
        await ch.send("12345", "hello", {"sender_id": "12345"})
        ch._call_api.assert_called_once_with(
            "send_private_msg",
            {
                "user_id": 12345,
                "message": [{"type": "text", "data": {"text": "hello"}}],
            },
        )

    async def test_group_message_send_via_meta(self):
        ch = _make_channel()
        ch._call_api = AsyncMock(return_value={"retcode": 0})
        await ch.send(
            "group:67890",
            "hello group",
            {"is_group": True, "group_id": "67890"},
        )
        ch._call_api.assert_called_once_with(
            "send_group_msg",
            {
                "group_id": 67890,
                "message": [{"type": "text", "data": {"text": "hello group"}}],
            },
        )

    async def test_group_message_send_via_to_handle(self):
        ch = _make_channel()
        ch._call_api = AsyncMock(return_value={"retcode": 0})
        await ch.send("group:67890", "hi")
        ch._call_api.assert_called_once()
        args = ch._call_api.call_args
        assert args[0][0] == "send_group_msg"
        assert args[0][1]["group_id"] == 67890

    async def test_send_cleans_link_markup_and_preserves_comments(self):
        ch = _make_channel()
        ch._call_api = AsyncMock(return_value={"retcode": 0})

        await ch.send(
            "12345",
            "为你找到了链接：\n**https://example.com/profile**\n"
            "[profile](https://example.com/card)\n"
            "`[inline](https://example.com/inline)`\n"
            "```\n**https://example.com/code**\n```\n"
            "<!-- internal lookup note -->",
            {"sender_id": "12345"},
        )

        args = ch._call_api.call_args[0]
        assert args[0] == "send_private_msg"
        assert args[1]["message"] == [
            {
                "type": "text",
                "data": {
                    "text": "为你找到了链接：\n"
                    "https://example.com/profile\n"
                    "profile: https://example.com/card\n"
                    "`[inline](https://example.com/inline)`\n"
                    "```\n**https://example.com/code**\n```\n"
                    "<!-- internal lookup note -->",
                },
            },
        ]

    def test_normalize_media_ref_policy(self, tmp_path):
        image = tmp_path / "pic.png"
        image.write_bytes(b"fake")

        assert (
            _normalize_media_ref_sync(
                image.as_uri(),
                media_base64_max_bytes=10 * 1024 * 1024,
            )
            == image.as_uri()
        )
        assert (
            _normalize_media_ref_sync(
                image.as_uri(),
                media_base64=True,
                media_base64_max_bytes=10 * 1024 * 1024,
            )
            == "base64://ZmFrZQ=="
        )
        assert (
            _normalize_media_ref_sync(
                image.as_uri(),
                media_base64=True,
                media_base64_max_bytes=1,
            )
            == image.as_uri()
        )
        assert (
            _normalize_media_ref_sync(
                "data:image/png;base64,ZmFrZQ==",
                media_base64_max_bytes=10 * 1024 * 1024,
            )
            == "base64://ZmFrZQ=="
        )


class TestSendMedia:
    async def test_send_image(self):
        from qwenpaw.schemas import (
            ImageContent,
        )

        ch = _make_channel()
        ch._call_api = AsyncMock(return_value={"retcode": 0})
        part = ImageContent(
            type=ContentType.IMAGE,
            image_url="https://img.example.com/pic.png",
        )
        await ch.send_media("12345", part, {"sender_id": "12345"})
        ch._call_api.assert_called_once()
        args = ch._call_api.call_args[0]
        assert args[0] == "send_private_msg"
        assert args[1]["message"][0]["type"] == "image"

    async def test_send_audio(self):
        from qwenpaw.schemas import (
            AudioContent,
        )

        ch = _make_channel()
        ch._call_api = AsyncMock(return_value={"retcode": 0})
        part = AudioContent(type=ContentType.AUDIO, data="https://a.com/v.mp3")
        await ch.send_media("12345", part, {"sender_id": "12345"})
        ch._call_api.assert_called_once()
        args = ch._call_api.call_args[0]
        assert args[1]["message"][0]["type"] == "record"

    async def test_send_video(self):
        from qwenpaw.schemas import (
            VideoContent,
        )

        ch = _make_channel()
        ch._call_api = AsyncMock(return_value={"retcode": 0})
        part = VideoContent(
            type=ContentType.VIDEO,
            video_url="https://v.com/v.mp4",
        )
        await ch.send_media("12345", part, {"sender_id": "12345"})
        ch._call_api.assert_called_once()
        args = ch._call_api.call_args[0]
        assert args[1]["message"][0]["type"] == "video"

    async def test_send_file_private(self):
        from qwenpaw.schemas import (
            FileContent,
        )

        ch = _make_channel()
        ch._call_api = AsyncMock(return_value={"retcode": 0})
        part = FileContent(
            type=ContentType.FILE,
            file_url="https://f.com/doc.pdf",
            filename="doc.pdf",
        )
        await ch.send_media("12345", part, {"sender_id": "12345"})
        ch._call_api.assert_called_once_with(
            "upload_private_file",
            {
                "user_id": 12345,
                "file": "https://f.com/doc.pdf",
                "name": "doc.pdf",
            },
        )

    async def test_send_file_to_group(self):
        from qwenpaw.schemas import (
            FileContent,
        )

        ch = _make_channel()
        ch._call_api = AsyncMock(return_value={"retcode": 0})
        part = FileContent(
            type=ContentType.FILE,
            file_url="https://f.com/report.xlsx",
            filename="report.xlsx",
        )
        await ch.send_media(
            "group:67890",
            part,
            {"is_group": True, "group_id": "67890"},
        )
        ch._call_api.assert_called_once_with(
            "upload_group_file",
            {
                "group_id": 67890,
                "file": "https://f.com/report.xlsx",
                "name": "report.xlsx",
            },
        )

    async def test_send_file_converts_local_path_when_enabled(self, tmp_path):
        from qwenpaw.schemas import FileContent

        file_path = tmp_path / "report.txt"
        file_path.write_bytes(b"fake")
        ch = _make_channel(media_base64=True)
        ch._call_api = AsyncMock(return_value={"retcode": 0})

        await ch.send_media(
            "12345",
            FileContent(file_url=file_path.as_uri(), filename="report.txt"),
            {"sender_id": "12345"},
        )

        assert ch._call_api.call_args.args[1]["file"] == "base64://ZmFrZQ=="

    async def test_send_file_no_url_noop(self):
        from qwenpaw.schemas import (
            FileContent,
        )

        ch = _make_channel()
        ch._call_api = AsyncMock()
        part = FileContent(type=ContentType.FILE, file_url="")
        await ch.send_media("12345", part, {"sender_id": "12345"})
        ch._call_api.assert_not_called()

    async def test_send_image_to_group(self):
        from qwenpaw.schemas import (
            ImageContent,
        )

        ch = _make_channel()
        ch._call_api = AsyncMock(return_value={"retcode": 0})
        part = ImageContent(
            type=ContentType.IMAGE,
            image_url="https://img.example.com/pic.png",
        )
        await ch.send_media(
            "group:67890",
            part,
            {"is_group": True, "group_id": "67890"},
        )
        args = ch._call_api.call_args[0]
        assert args[0] == "send_group_msg"
        assert args[1]["group_id"] == 67890

    async def test_send_content_parts_preserves_order_and_prefix(self):
        from qwenpaw.schemas import ImageContent

        ch = _make_channel()
        ch._call_api = AsyncMock(return_value={"retcode": 0})

        await ch.send_content_parts(
            "12345",
            [
                TextContent(type=ContentType.TEXT, text="这是截图"),
                ImageContent(
                    type=ContentType.IMAGE,
                    image_url="https://img.example.com/pic.png",
                ),
                TextContent(type=ContentType.TEXT, text="补充说明"),
            ],
            {"sender_id": "12345", "bot_prefix": "[BOT]"},
        )

        assert ch._call_api.call_count == 3
        first = ch._call_api.call_args_list[0][0]
        second = ch._call_api.call_args_list[1][0]
        third = ch._call_api.call_args_list[2][0]
        assert first == (
            "send_private_msg",
            {
                "user_id": 12345,
                "message": [
                    {"type": "text", "data": {"text": "[BOT]  这是截图"}},
                ],
            },
        )
        assert second == (
            "send_private_msg",
            {
                "user_id": 12345,
                "message": [
                    {
                        "type": "image",
                        "data": {"file": "https://img.example.com/pic.png"},
                    },
                ],
            },
        )
        assert third == (
            "send_private_msg",
            {
                "user_id": 12345,
                "message": [
                    {"type": "text", "data": {"text": "补充说明"}},
                ],
            },
        )


# ===================================================================
# Echo-based API calls
# ===================================================================


class TestCallApi:
    async def test_no_connections_returns_empty(self):
        ch = _make_channel()
        result = await ch._call_api("get_login_info", {})
        assert result == {}

    async def test_successful_call(self):
        ch = _make_channel()
        ws = AsyncMock()
        ch._connections.add(ws)

        async def simulate_response():
            await asyncio.sleep(0.01)
            # Find the pending echo and resolve it
            for echo, fut in list(ch._pending_calls.items()):
                if not fut.done():
                    fut.set_result(
                        {"retcode": 0, "data": {"user_id": 99}, "echo": echo},
                    )

        task = asyncio.create_task(simulate_response())
        result = await ch._call_api("get_login_info", {})
        await task
        assert result.get("retcode") == 0

    async def test_timeout_returns_empty(self):
        ch = _make_channel()
        ws = AsyncMock()
        ch._connections.add(ws)

        # Don't resolve the future — will timeout
        # Use a very short timeout for testing
        import unittest.mock

        with unittest.mock.patch(
            "asyncio.wait_for",
            side_effect=asyncio.TimeoutError,
        ):
            result = await ch._call_api("slow_action", {})
        assert result == {}


class TestHandleApiResponse:
    def test_matching_echo_resolves_future(self):
        ch = _make_channel()
        loop = asyncio.new_event_loop()
        fut = loop.create_future()
        ch._pending_calls["abc-123"] = fut

        ch._handle_api_response(
            {"retcode": 0, "data": {}, "echo": "abc-123"},
        )
        assert fut.done()
        assert fut.result()["retcode"] == 0
        loop.close()

    def test_unknown_echo_ignored(self):
        ch = _make_channel()
        # Should not raise
        ch._handle_api_response({"retcode": 0, "echo": "unknown"})


# ===================================================================
# Meta event handling
# ===================================================================


class TestHandleMetaEvent:
    def test_lifecycle_connect_sets_self_id(self):
        ch = _make_channel()
        ch._handle_meta_event(
            {
                "post_type": "meta_event",
                "meta_event_type": "lifecycle",
                "sub_type": "connect",
                "self_id": 99999,
            },
        )
        assert ch._self_id == 99999

    def test_heartbeat_does_not_crash(self):
        ch = _make_channel()
        ch._handle_meta_event(
            {
                "post_type": "meta_event",
                "meta_event_type": "heartbeat",
                "self_id": 99999,
            },
        )


# ===================================================================
# Event dispatch
# ===================================================================


class TestHandleEvent:
    async def test_meta_event_dispatched(self):
        ch = _make_channel()
        await ch._handle_event(
            {
                "post_type": "meta_event",
                "meta_event_type": "lifecycle",
                "sub_type": "connect",
                "self_id": 88888,
            },
        )
        assert ch._self_id == 88888

    async def test_message_event_dispatched(self):
        ch = _make_channel()
        enqueued: list = []
        ch._enqueue = enqueued.append

        await ch._handle_event(
            _make_message_event(message_type="private", user_id=11111),
        )
        assert len(enqueued) == 1

    async def test_notice_event_ignored(self):
        ch = _make_channel()
        enqueued: list = []
        ch._enqueue = enqueued.append

        await ch._handle_event({"post_type": "notice", "notice_type": "poke"})
        assert len(enqueued) == 0


# ===================================================================
# build_agent_request_from_native
# ===================================================================


class TestBuildAgentRequest:
    def test_basic_request(self):
        ch = _make_channel()
        native = {
            "channel_id": "onebot",
            "sender_id": "12345",
            "content_parts": [
                TextContent(type=ContentType.TEXT, text="hi"),
            ],
            "meta": {"is_group": False},
        }
        req = ch.build_agent_request_from_native(native)
        assert req.session_id == "onebot:12345"
        assert req.user_id == "12345"
        assert req.channel == "onebot"
        assert len(req.input) == 1
        assert req.input[0].content[0].text == "hi"


# ===================================================================
# Lifecycle
# ===================================================================


class TestLifecycle:
    async def test_disabled_start_noop(self):
        ch = _make_channel(enabled=False)
        await ch.start()
        assert ch._app is None

    async def test_disabled_stop_noop(self):
        ch = _make_channel(enabled=False)
        await ch.stop()

    async def test_start_creates_server(self):
        ch = _make_channel(ws_port=0)  # port 0 = OS picks free port
        await ch.start()
        assert ch._app is not None
        assert ch._runner is not None
        assert ch._site is not None
        assert ch._watchdog_task is not None
        assert not ch._watchdog_task.done()
        await ch.stop()
        assert ch._site is None
        assert ch._runner is None
        assert ch._stopping is True


# ===================================================================
# Watchdog / reconnect
# ===================================================================


class TestWatchdog:
    async def test_watchdog_restarts_when_site_is_none(self):
        """Watchdog should restart the WS server if _site becomes None."""
        ch = _make_channel(ws_port=0)
        ch._watchdog_interval = 0.05  # speed up for test
        await ch.start()
        assert ch._site is not None

        # Simulate server crash: clear server state without full stop
        old_site = ch._site
        await old_site.stop()
        await ch._runner.cleanup()
        ch._site = None
        ch._runner = None
        ch._app = None

        # Wait for watchdog to detect and restart
        await asyncio.sleep(0.2)

        assert ch._site is not None, "watchdog should have restarted server"
        assert ch._app is not None
        assert ch._runner is not None

        await ch.stop()

    async def test_watchdog_restarts_when_port_unreachable(self):
        """Watchdog should restart if _site exists but port is dead."""
        ch = _make_channel(ws_port=0)
        ch._watchdog_interval = 0.05
        await ch.start()
        assert ch._site is not None

        # Simulate TCPSite still exists but underlying socket is dead:
        # stop the site but keep the Python object reference
        old_site = ch._site
        await old_site.stop()
        # _site is NOT None, but the port is no longer listening

        # Wait for watchdog to detect via TCP probe and restart
        await asyncio.sleep(0.3)

        assert ch._site is not None
        assert (
            ch._site is not old_site
        ), "watchdog should have created a new site"

        await ch.stop()

    async def test_watchdog_stops_on_channel_stop(self):
        """Watchdog task should be cancelled when channel stops."""
        ch = _make_channel(ws_port=0)
        ch._watchdog_interval = 0.05
        await ch.start()
        watchdog = ch._watchdog_task
        assert watchdog is not None

        await ch.stop()
        assert watchdog.done()

    async def test_watchdog_no_restart_when_healthy(self):
        """Watchdog should not touch a healthy server."""
        ch = _make_channel(ws_port=0)
        ch._watchdog_interval = 0.05
        await ch.start()
        original_site = ch._site

        # Wait a couple of watchdog cycles
        await asyncio.sleep(0.15)

        # Site should remain the same object (not recreated)
        assert ch._site is original_site
        await ch.stop()

    async def test_is_server_healthy_when_listening(self):
        """_is_server_healthy returns True when port is accepting."""
        ch = _make_channel(ws_port=0)
        await ch._start_ws_server()
        assert await ch._is_server_healthy() is True
        await ch._stop_ws_server()

    async def test_is_server_healthy_when_site_none(self):
        """_is_server_healthy returns False when _site is None."""
        ch = _make_channel(ws_port=0)
        assert await ch._is_server_healthy() is False


# ===================================================================
# Preview helper
# ===================================================================


class TestPreviewText:
    def test_text_content(self):
        parts = [TextContent(type=ContentType.TEXT, text="hello world")]
        assert OneBotChannel._preview_text(parts) == "hello world"

    def test_non_text_content(self):
        from qwenpaw.schemas import (
            ImageContent,
        )

        parts = [
            ImageContent(
                type=ContentType.IMAGE,
                image_url="https://x.com/i.png",
            ),
        ]
        assert OneBotChannel._preview_text(parts) == "<non-text>"

    def test_empty_parts(self):
        assert OneBotChannel._preview_text([]) == "<non-text>"


# ===================================================================
# Port bind retry during _start_ws_server
# ===================================================================


class TestPortBindGracefulDegradation:
    """Tests for graceful degradation when port is in use."""

    async def test_port_conflict_does_not_raise(self):
        """_start_ws_server should not raise on OSError (port in use).

        It should clean up and leave _site as None so the watchdog
        can retry later.
        """
        ch = _make_channel(ws_port=0)

        from unittest.mock import patch
        from aiohttp.web import TCPSite

        async def always_fail(self_site):
            raise OSError(98, "address already in use")

        with patch.object(TCPSite, "start", always_fail):
            # Should NOT raise
            await ch._start_ws_server()

        # State should be cleaned up for watchdog recovery
        assert ch._site is None
        assert ch._runner is None
        assert ch._app is None

    async def test_watchdog_recovers_after_port_conflict(self):
        """Watchdog should recover the server after initial port conflict."""
        ch = _make_channel(ws_port=0)
        ch._watchdog_interval = 0.05

        from unittest.mock import patch
        from aiohttp.web import TCPSite

        fail_count = 1
        original_tcp_start = TCPSite.start

        async def mock_site_start(self_site):
            nonlocal fail_count
            if fail_count > 0:
                fail_count -= 1
                raise OSError(98, "address already in use")
            return await original_tcp_start(self_site)

        with patch.object(TCPSite, "start", mock_site_start):
            await ch.start()
            # Initial start failed, _site is None
            assert ch._site is None

        # Watchdog should recover (no patch, real start succeeds)
        await asyncio.sleep(0.3)
        assert ch._site is not None

        await ch.stop()

    async def test_non_oserror_still_raises(self):
        """Non-OSError exceptions should propagate normally."""
        ch = _make_channel(ws_port=0)

        from unittest.mock import patch
        from aiohttp.web import TCPSite

        async def fail_with_runtime_error(self_site):
            raise RuntimeError("unexpected error")

        with patch.object(TCPSite, "start", fail_with_runtime_error):
            try:
                await ch._start_ws_server()
                assert False, "Should have raised RuntimeError"
            except RuntimeError:
                pass


class _ReachedAccept(Exception):
    """Sentinel proving a handshake passed every authentication guard."""


class TestConnectionAuth:
    """Tests for reverse WebSocket handshake authentication."""

    @staticmethod
    def _request(path: str = "/ws", authorization: str | None = None):
        headers = (
            {} if authorization is None else {"Authorization": authorization}
        )
        return make_mocked_request("GET", path, headers=headers)

    @staticmethod
    def _sentinel_prepare():
        """Patch ``prepare`` so reaching it raises :class:`_ReachedAccept`.

        ``prepare`` runs right after the authentication guards, so the
        sentinel distinguishes "accepted" from "rejected" without a real
        WebSocket upgrade.
        """
        from unittest.mock import patch

        async def _prepare(_self, _request):
            raise _ReachedAccept

        return patch.object(web.WebSocketResponse, "prepare", _prepare)

    async def test_non_loopback_without_token_rejects_connection(
        self,
        caplog,
    ):
        """The server keeps listening but refuses every client."""
        ch = _make_channel(ws_host="0.0.0.0", access_token="")

        with caplog.at_level(logging.ERROR):
            resp = await ch._handle_ws_connection(self._request())

        assert resp.status == 401
        assert not ch._connections
        assert "access_token is empty" in caplog.text

    async def test_loopback_without_token_accepts_connection(self):
        """Existing local setups keep working without a token."""
        ch = _make_channel(ws_host="127.0.0.1", access_token="")

        with self._sentinel_prepare():
            with pytest.raises(_ReachedAccept):
                await ch._handle_ws_connection(self._request())

    async def test_non_loopback_with_valid_token_accepts_connection(self):
        """Exposing the port is allowed once a token is configured."""
        ch = _make_channel(ws_host="0.0.0.0", access_token="s3cret-token")
        request = self._request(authorization="Bearer s3cret-token")

        with self._sentinel_prepare():
            with pytest.raises(_ReachedAccept):
                await ch._handle_ws_connection(request)

    @pytest.mark.parametrize(
        "authorization",
        [
            "Bearer s3cret-token",
            "Token s3cret-token",
            "bearer s3cret-token",
        ],
    )
    def test_accepted_authorization_schemes(self, authorization: str):
        """Bearer and Token are accepted, case-insensitively."""
        ch = _make_channel(access_token="s3cret-token")
        request = self._request(authorization=authorization)
        assert ch._token_authorized(request) is True

    @pytest.mark.parametrize(
        "authorization",
        [
            "Bearer wrong-token",
            "Basic s3cret-token",
            "s3cret-token",
            "Bearer",
            "",
        ],
    )
    def test_rejected_authorization_headers(self, authorization: str):
        ch = _make_channel(access_token="s3cret-token")
        request = self._request(authorization=authorization)
        assert ch._token_authorized(request) is False

    async def test_query_parameter_rejection_logs_migration_hint(
        self,
        caplog,
    ):
        """Query tokens are not accepted; the log explains the migration."""
        ch = _make_channel(ws_host="0.0.0.0", access_token="s3cret-token")
        request = self._request(path="/ws?access_token=s3cret-token")

        with caplog.at_level(logging.WARNING):
            resp = await ch._handle_ws_connection(request)

        assert resp.status == 401
        assert "Authorization header" in caplog.text

    def test_non_ascii_token_is_supported(self):
        """compare_digest requires bytes for non-ASCII tokens."""
        token = "密钥-abc"
        ch = _make_channel(access_token=token)
        request = self._request(authorization=f"Bearer {token}")
        assert ch._token_authorized(request) is True

    async def test_rejection_log_stays_on_one_line(self, caplog):
        """A forged newline must not become a second log record."""
        ch = _make_channel(ws_host="0.0.0.0", access_token="")
        request = self._request().clone(
            remote="1.2.3.4\nINFO onebot: client connected from 1.2.3.4",
        )

        with caplog.at_level(logging.ERROR):
            resp = await ch._handle_ws_connection(request)

        assert resp.status == 401
        assert len(caplog.records) == 1
        assert "\n" not in caplog.records[0].getMessage()


class TestDefaultBindAddress:
    """Tests for the loopback-by-default listen address."""

    def test_config_default_is_loopback(self):
        assert OneBotConfig().ws_host == "127.0.0.1"

    def test_channel_default_is_loopback(self):
        async def _noop_process(_request):
            yield  # pragma: no cover

        ch = OneBotChannel(process=_noop_process, enabled=True)

        assert ch._ws_host == "127.0.0.1"
        assert ch._auth_required is False

    @pytest.mark.parametrize("ws_host", ["", "   "])
    def test_blank_host_normalizes_to_loopback(self, ws_host: str):
        """A blank host must not fall through to every interface."""
        ch = _make_channel(ws_host=ws_host)

        assert ch._ws_host == "127.0.0.1"
        assert ch._auth_required is False

    def test_bracketed_ipv6_host_is_unwrapped(self):
        """Brackets are URL notation and make getaddrinfo fail."""
        ch = _make_channel(ws_host="[::1]")

        assert ch._ws_host == "::1"
        assert ch._auth_required is False

    def test_whitespace_token_counts_as_unset(self):
        """A whitespace token could never match a stripped request token."""
        ch = _make_channel(ws_host="0.0.0.0", access_token="   ")

        assert ch._access_token == ""
        assert ch._auth_required is True
