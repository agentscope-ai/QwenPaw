# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for OneBot v11 channel."""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from agentscope_runtime.engine.schemas.agent_schemas import (
    ContentType,
    TextContent,
)

from copaw.app.channels.onebot.channel import OneBotChannel


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
        "ws_host": "0.0.0.0",
        "ws_port": 6199,
        "access_token": "",
        "bot_prefix": "",
    }
    defaults.update(overrides)
    return OneBotChannel(**defaults)


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

    async def test_allowlist_blocks_unknown_user(self):
        ch = _make_channel(
            dm_policy="allowlist",
            allow_from=["99999"],
        )
        ch._enqueue = MagicMock()
        ch.send = AsyncMock()

        event = _make_message_event(user_id=12345)
        await ch._handle_message_event(event)

        ch._enqueue.assert_not_called()
        ch.send.assert_called_once()  # deny message sent

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


class TestSendMedia:
    async def test_send_image(self):
        from agentscope_runtime.engine.schemas.agent_schemas import (
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
        from agentscope_runtime.engine.schemas.agent_schemas import (
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
        from agentscope_runtime.engine.schemas.agent_schemas import (
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

    async def test_send_unsupported_type_noop(self):
        from agentscope_runtime.engine.schemas.agent_schemas import (
            FileContent,
        )

        ch = _make_channel()
        ch._call_api = AsyncMock()
        part = FileContent(
            type=ContentType.FILE,
            file_url="https://f.com/doc.pdf",
        )
        await ch.send_media("12345", part, {"sender_id": "12345"})
        ch._call_api.assert_not_called()

    async def test_send_image_to_group(self):
        from agentscope_runtime.engine.schemas.agent_schemas import (
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
        await ch.stop()
        assert ch._site is None
        assert ch._runner is None


# ===================================================================
# Preview helper
# ===================================================================


class TestPreviewText:
    def test_text_content(self):
        parts = [TextContent(type=ContentType.TEXT, text="hello world")]
        assert OneBotChannel._preview_text(parts) == "hello world"

    def test_non_text_content(self):
        from agentscope_runtime.engine.schemas.agent_schemas import (
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
