# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for QQ channel."""
from __future__ import annotations

import json
import threading
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentscope_runtime.engine.schemas.agent_schemas import (
    TextContent,
)

from copaw.app.channels.qq.channel import (
    QQApiError,
    QQChannel,
    _as_bool,
    _get_next_msg_seq,
    _HeartbeatController,
    _media_path,
    _MESSAGE_EVENT_SPECS,
    _sanitize_qq_text,
    _send_message_async,
    _should_plaintext_fallback_from_markdown,
    _WSState,
    MAX_QUICK_DISCONNECT_COUNT,
    OP_DISPATCH,
    OP_HEARTBEAT_ACK,
    OP_HELLO,
    OP_IDENTIFY,
    OP_INVALID_SESSION,
    OP_RECONNECT,
    OP_RESUME,
    RATE_LIMIT_DELAY,
    RECONNECT_DELAYS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_channel(**overrides: Any) -> QQChannel:
    """Create a QQChannel with dummy process handler."""

    async def _noop_process(_request):
        yield  # pragma: no cover

    defaults = {
        "process": _noop_process,
        "enabled": True,
        "app_id": "test_app_id",
        "client_secret": "test_secret",
        "bot_prefix": "",
        "markdown_enabled": True,
    }
    defaults.update(overrides)
    ch = QQChannel(**defaults)
    ch._http = MagicMock()
    return ch


# ===================================================================
# Module-level utility functions
# ===================================================================


class TestSanitizeQQText:
    def test_empty_string(self):
        assert _sanitize_qq_text("") == ("", False)

    def test_no_url(self):
        assert _sanitize_qq_text("hello world") == ("hello world", False)

    def test_single_url(self):
        text, removed = _sanitize_qq_text("visit https://example.com now")
        assert removed is True
        assert "https://example.com" not in text
        assert "[链接已省略]" in text

    def test_multiple_urls(self):
        text, removed = _sanitize_qq_text(
            "see https://a.com and http://b.com",
        )
        assert removed is True
        assert text.count("[链接已省略]") == 2


class TestAsBool:
    @pytest.mark.parametrize(
        "val,expected",
        [
            (True, True),
            (False, False),
            ("1", True),
            ("true", True),
            ("True", True),
            ("yes", True),
            ("on", True),
            ("0", False),
            ("false", False),
            ("no", False),
            ("", False),
            (1, True),
            (0, False),
        ],
    )
    def test_values(self, val, expected):
        assert _as_bool(val) is expected


class TestShouldPlaintextFallback:
    def test_non_qq_api_error(self):
        assert (
            _should_plaintext_fallback_from_markdown(
                RuntimeError("boom"),
            )
            is False
        )

    def test_server_error_status(self):
        err = QQApiError("/test", 500, {"error": "markdown"})
        assert _should_plaintext_fallback_from_markdown(err) is False

    def test_status_below_400(self):
        err = QQApiError("/test", 200, {"error": "markdown"})
        assert _should_plaintext_fallback_from_markdown(err) is False

    def test_markdown_in_data(self):
        err = QQApiError("/test", 400, {"error": "invalid markdown"})
        assert _should_plaintext_fallback_from_markdown(err) is True

    def test_msg_type_in_data(self):
        err = QQApiError("/test", 422, {"error": "bad msg_type"})
        assert _should_plaintext_fallback_from_markdown(err) is True

    def test_no_markdown_keyword(self):
        err = QQApiError("/test", 400, {"error": "rate limit"})
        assert _should_plaintext_fallback_from_markdown(err) is False


class TestGetNextMsgSeq:
    def test_increments(self):
        key = f"__test_seq_{time.time()}"
        assert _get_next_msg_seq(key) == 1
        assert _get_next_msg_seq(key) == 2
        assert _get_next_msg_seq(key) == 3


class TestMediaPath:
    def test_c2c(self):
        assert _media_path("c2c", "uid123", "files") == (
            "/v2/users/uid123/files"
        )

    def test_group(self):
        assert _media_path("group", "gid456", "messages") == (
            "/v2/groups/gid456/messages"
        )

    def test_unsupported(self):
        assert _media_path("guild", "id", "files") is None


class TestQQApiError:
    def test_attributes(self):
        err = QQApiError("/path", 400, {"msg": "bad"})
        assert err.path == "/path"
        assert err.status == 400
        assert err.data == {"msg": "bad"}
        assert "400" in str(err)


# ===================================================================
# _WSState
# ===================================================================


class TestWSState:
    def test_defaults(self):
        s = _WSState()
        assert s.session_id is None
        assert s.last_seq is None
        assert s.reconnect_attempts == 0
        assert s.quick_disconnect_count == 0
        assert s.identify_fail_count == 0
        assert s.should_refresh_token is False

    def test_mutable(self):
        s = _WSState()
        s.session_id = "abc"
        s.last_seq = 42
        assert s.session_id == "abc"
        assert s.last_seq == 42


# ===================================================================
# _MessageEventSpec lookup table
# ===================================================================


class TestMessageEventSpecs:
    def test_all_four_types_present(self):
        expected = {
            "C2C_MESSAGE_CREATE",
            "AT_MESSAGE_CREATE",
            "DIRECT_MESSAGE_CREATE",
            "GROUP_AT_MESSAGE_CREATE",
        }
        assert set(_MESSAGE_EVENT_SPECS.keys()) == expected

    def test_c2c_spec(self):
        spec = _MESSAGE_EVENT_SPECS["C2C_MESSAGE_CREATE"]
        assert spec.message_type == "c2c"
        assert "user_openid" in spec.sender_keys
        assert spec.extra_meta_keys == ()

    def test_guild_spec(self):
        spec = _MESSAGE_EVENT_SPECS["AT_MESSAGE_CREATE"]
        assert spec.message_type == "guild"
        assert "channel_id" in spec.extra_meta_keys
        assert "guild_id" in spec.extra_meta_keys

    def test_group_spec(self):
        spec = _MESSAGE_EVENT_SPECS["GROUP_AT_MESSAGE_CREATE"]
        assert spec.message_type == "group"
        assert "group_openid" in spec.extra_meta_keys


# ===================================================================
# _HeartbeatController
# ===================================================================


class TestHeartbeatController:
    def test_start_and_stop(self):
        ws = MagicMock(connected=True)
        stop_event = threading.Event()
        state = _WSState(last_seq=5)
        hb = _HeartbeatController(ws, stop_event, state)
        hb.start(50000)  # 50s interval
        assert hb._timer is not None
        hb.stop()
        assert hb._timer is None

    def test_stop_when_no_timer(self):
        ws = MagicMock()
        hb = _HeartbeatController(ws, threading.Event(), _WSState())
        hb.stop()  # should not raise

    def test_no_schedule_when_stopped(self):
        ws = MagicMock()
        stop_event = threading.Event()
        stop_event.set()
        state = _WSState()
        hb = _HeartbeatController(ws, stop_event, state)
        hb.start(1000)
        assert hb._timer is None  # stop_event was set, no timer


# ===================================================================
# _compute_reconnect_delay
# ===================================================================


class TestComputeReconnectDelay:
    def test_first_attempt(self):
        ch = _make_channel()
        state = _WSState(reconnect_attempts=0)
        delay = ch._compute_reconnect_delay(state)
        assert delay == RECONNECT_DELAYS[0]

    def test_escalating_delay(self):
        ch = _make_channel()
        state = _WSState(reconnect_attempts=3)
        delay = ch._compute_reconnect_delay(state)
        assert delay == RECONNECT_DELAYS[3]

    def test_max_delay_clamped(self):
        ch = _make_channel()
        state = _WSState(reconnect_attempts=999)
        delay = ch._compute_reconnect_delay(state)
        assert delay == RECONNECT_DELAYS[-1]

    def test_quick_disconnect_triggers_rate_limit(self):
        ch = _make_channel()
        state = _WSState(
            last_connect_time=time.time() - 1,  # <5s ago
            quick_disconnect_count=MAX_QUICK_DISCONNECT_COUNT - 1,
        )
        delay = ch._compute_reconnect_delay(state)
        assert delay == RATE_LIMIT_DELAY
        assert state.should_refresh_token is True
        assert state.session_id is None

    def test_normal_disconnect_resets_quick_count(self):
        ch = _make_channel()
        state = _WSState(
            last_connect_time=time.time() - 100,  # long ago
            quick_disconnect_count=2,
        )
        ch._compute_reconnect_delay(state)
        assert state.quick_disconnect_count == 0


# ===================================================================
# _handle_ws_payload
# ===================================================================


class TestHandleWsPayload:
    def _make_deps(self):
        ch = _make_channel()
        ws = MagicMock()
        state = _WSState()
        hb = MagicMock()
        return ch, ws, state, hb

    def test_hello_sends_identify(self):
        ch, ws, state, hb = self._make_deps()
        payload = {
            "op": OP_HELLO,
            "d": {"heartbeat_interval": 45000},
            "s": None,
            "t": None,
        }
        result = ch._handle_ws_payload(payload, ws, "tok", state, hb)
        assert result is None
        ws.send.assert_called_once()
        sent = json.loads(ws.send.call_args[0][0])
        assert sent["op"] == OP_IDENTIFY
        hb.start.assert_called_once_with(45000)

    def test_hello_sends_resume_when_session_exists(self):
        ch, ws, state, hb = self._make_deps()
        state.session_id = "sess_123"
        state.last_seq = 42
        payload = {
            "op": OP_HELLO,
            "d": {"heartbeat_interval": 30000},
            "s": None,
            "t": None,
        }
        result = ch._handle_ws_payload(payload, ws, "tok", state, hb)
        assert result is None
        sent = json.loads(ws.send.call_args[0][0])
        assert sent["op"] == OP_RESUME
        assert sent["d"]["session_id"] == "sess_123"
        assert sent["d"]["seq"] == 42

    def test_dispatch_ready(self):
        ch, ws, state, hb = self._make_deps()
        payload = {
            "op": OP_DISPATCH,
            "d": {"session_id": "new_sess"},
            "s": 1,
            "t": "READY",
        }
        result = ch._handle_ws_payload(payload, ws, "tok", state, hb)
        assert result is None
        assert state.session_id == "new_sess"
        assert state.last_seq == 1

    def test_dispatch_message_calls_handle_msg_event(self):
        ch, ws, state, hb = self._make_deps()
        ch._handle_msg_event = MagicMock()
        payload = {
            "op": OP_DISPATCH,
            "d": {"author": {"user_openid": "u1"}, "content": "hi"},
            "s": 5,
            "t": "C2C_MESSAGE_CREATE",
        }
        result = ch._handle_ws_payload(payload, ws, "tok", state, hb)
        assert result is None
        ch._handle_msg_event.assert_called_once_with(
            "C2C_MESSAGE_CREATE",
            {"author": {"user_openid": "u1"}, "content": "hi"},
        )

    def test_heartbeat_ack(self):
        ch, ws, state, hb = self._make_deps()
        payload = {"op": OP_HEARTBEAT_ACK, "d": None, "s": None, "t": None}
        result = ch._handle_ws_payload(payload, ws, "tok", state, hb)
        assert result is None

    def test_reconnect_returns_break(self):
        ch, ws, state, hb = self._make_deps()
        payload = {"op": OP_RECONNECT, "d": None, "s": None, "t": None}
        result = ch._handle_ws_payload(payload, ws, "tok", state, hb)
        assert result == "break"

    def test_invalid_session_not_resumable(self):
        ch, ws, state, hb = self._make_deps()
        state.session_id = "old"
        state.last_seq = 10
        payload = {"op": OP_INVALID_SESSION, "d": False, "s": None, "t": None}
        result = ch._handle_ws_payload(payload, ws, "tok", state, hb)
        assert result == "break"
        assert state.session_id is None
        assert state.last_seq is None
        assert state.should_refresh_token is True

    def test_invalid_session_resumable(self):
        ch, ws, state, hb = self._make_deps()
        state.session_id = "old"
        state.last_seq = 10
        payload = {"op": OP_INVALID_SESSION, "d": True, "s": None, "t": None}
        result = ch._handle_ws_payload(payload, ws, "tok", state, hb)
        assert result == "break"
        # session preserved when resumable
        assert state.session_id == "old"
        assert state.last_seq == 10

    def test_seq_updated(self):
        ch, ws, state, hb = self._make_deps()
        payload = {"op": OP_HEARTBEAT_ACK, "d": None, "s": 99, "t": None}
        ch._handle_ws_payload(payload, ws, "tok", state, hb)
        assert state.last_seq == 99

    def test_unknown_op(self):
        ch, ws, state, hb = self._make_deps()
        payload = {"op": 999, "d": None, "s": None, "t": None}
        result = ch._handle_ws_payload(payload, ws, "tok", state, hb)
        assert result is None


# ===================================================================
# _handle_msg_event
# ===================================================================


class TestHandleMsgEvent:
    def test_c2c_message_enqueues(self):
        ch = _make_channel()
        enqueued: list = []
        ch._enqueue = enqueued.append
        d = {
            "author": {"user_openid": "sender_1", "id": "fallback_id"},
            "content": "hello",
            "id": "msg_001",
            "attachments": [],
        }
        ch._handle_msg_event("C2C_MESSAGE_CREATE", d)
        assert len(enqueued) == 1
        req = enqueued[0]
        assert req.channel_meta["message_type"] == "c2c"
        assert req.channel_meta["sender_id"] == "sender_1"

    def test_guild_message_has_extra_meta(self):
        ch = _make_channel()
        enqueued: list = []
        ch._enqueue = enqueued.append
        d = {
            "author": {"id": "author_1"},
            "content": "hello guild",
            "id": "msg_002",
            "channel_id": "ch_100",
            "guild_id": "g_200",
        }
        ch._handle_msg_event("AT_MESSAGE_CREATE", d)
        assert len(enqueued) == 1
        meta = enqueued[0].channel_meta
        assert meta["message_type"] == "guild"
        assert meta["channel_id"] == "ch_100"
        assert meta["guild_id"] == "g_200"

    def test_group_message(self):
        ch = _make_channel()
        enqueued: list = []
        ch._enqueue = enqueued.append
        d = {
            "author": {"member_openid": "mem_1"},
            "content": "hi group",
            "id": "msg_003",
            "group_openid": "grp_300",
        }
        ch._handle_msg_event("GROUP_AT_MESSAGE_CREATE", d)
        assert len(enqueued) == 1
        meta = enqueued[0].channel_meta
        assert meta["message_type"] == "group"
        assert meta["group_openid"] == "grp_300"

    def test_empty_text_no_attachments_skipped(self):
        ch = _make_channel()
        enqueued: list = []
        ch._enqueue = enqueued.append
        d = {"author": {"user_openid": "u1"}, "content": "", "id": "m1"}
        ch._handle_msg_event("C2C_MESSAGE_CREATE", d)
        assert len(enqueued) == 0

    def test_bot_prefix_skipped(self):
        ch = _make_channel(bot_prefix="[BOT]")
        enqueued: list = []
        ch._enqueue = enqueued.append
        d = {
            "author": {"user_openid": "u1"},
            "content": "[BOT] response",
            "id": "m1",
        }
        ch._handle_msg_event("C2C_MESSAGE_CREATE", d)
        assert len(enqueued) == 0

    def test_no_sender_skipped(self):
        ch = _make_channel()
        enqueued: list = []
        ch._enqueue = enqueued.append
        d = {"author": {}, "content": "hello", "id": "m1"}
        ch._handle_msg_event("C2C_MESSAGE_CREATE", d)
        assert len(enqueued) == 0

    def test_unknown_event_type_ignored(self):
        ch = _make_channel()
        enqueued: list = []
        ch._enqueue = enqueued.append
        ch._handle_msg_event("UNKNOWN_EVENT", {"content": "hi"})
        assert len(enqueued) == 0

    def test_sender_fallback_to_second_key(self):
        """C2C: if user_openid missing, falls back to id."""
        ch = _make_channel()
        enqueued: list = []
        ch._enqueue = enqueued.append
        d = {
            "author": {"id": "fallback_id"},
            "content": "hello",
            "id": "m1",
        }
        ch._handle_msg_event("C2C_MESSAGE_CREATE", d)
        assert len(enqueued) == 1
        assert enqueued[0].channel_meta["sender_id"] == "fallback_id"


# ===================================================================
# _resolve_send_path
# ===================================================================


class TestResolveSendPath:
    def test_c2c(self):
        ch = _make_channel()
        path, use_seq, key = ch._resolve_send_path(
            "c2c",
            "sender_1",
            None,
            None,
        )
        assert path == "/v2/users/sender_1/messages"
        assert use_seq is True
        assert key == "c2c"

    def test_group(self):
        ch = _make_channel()
        path, use_seq, key = ch._resolve_send_path(
            "group",
            "sender_1",
            None,
            "grp_1",
        )
        assert path == "/v2/groups/grp_1/messages"
        assert use_seq is True
        assert key == "group"

    def test_guild(self):
        ch = _make_channel()
        path, use_seq, _key = ch._resolve_send_path(
            "guild",
            "sender_1",
            "ch_1",
            None,
        )
        assert path == "/channels/ch_1/messages"
        assert use_seq is False

    def test_fallback_to_c2c(self):
        ch = _make_channel()
        path, use_seq, _key = ch._resolve_send_path(
            "unknown",
            "sender_1",
            None,
            None,
        )
        assert "/v2/users/sender_1/" in path
        assert use_seq is True


# ===================================================================
# _resolve_attachment_type
# ===================================================================


class TestResolveAttachmentType:
    def test_by_extension(self):
        ch = _make_channel()
        assert ch._resolve_attachment_type("", "photo.jpg") == "image"
        assert ch._resolve_attachment_type("", "video.mp4") == "video"
        assert ch._resolve_attachment_type("", "song.mp3") == "audio"
        assert ch._resolve_attachment_type("", "doc.pdf") == "file"

    def test_direct_type(self):
        ch = _make_channel()
        assert ch._resolve_attachment_type("image", "") == "image"
        assert ch._resolve_attachment_type("video", "") == "video"
        assert ch._resolve_attachment_type("audio", "") == "audio"
        assert ch._resolve_attachment_type("file", "") == "file"

    def test_voice_maps_to_audio(self):
        ch = _make_channel()
        assert ch._resolve_attachment_type("voice", "") == "audio"

    def test_mime_type(self):
        ch = _make_channel()
        assert ch._resolve_attachment_type("image/jpeg", "") == "image"
        assert ch._resolve_attachment_type("video/mp4", "") == "video"
        assert (
            ch._resolve_attachment_type(
                "audio/mpeg; charset=utf-8",
                "",
            )
            == "audio"
        )

    def test_unknown_mime(self):
        ch = _make_channel()
        assert (
            ch._resolve_attachment_type(
                "application/pdf",
                "",
            )
            == "file"
        )


# ===================================================================
# _make_content_part
# ===================================================================


class TestMakeContentPart:
    def test_image(self):
        part = QQChannel._make_content_part("image", "/tmp/a.jpg", "a.jpg")
        assert part is not None
        assert part.image_url == "/tmp/a.jpg"

    def test_video(self):
        part = QQChannel._make_content_part("video", "/tmp/v.mp4", "v.mp4")
        assert part is not None
        assert part.video_url == "/tmp/v.mp4"

    def test_audio(self):
        part = QQChannel._make_content_part("audio", "/tmp/a.mp3", "a.mp3")
        assert part is not None
        assert part.data == "/tmp/a.mp3"

    def test_file(self):
        part = QQChannel._make_content_part("file", "/tmp/d.pdf", "d.pdf")
        assert part is not None
        assert part.file_url == "/tmp/d.pdf"
        assert part.filename == "d.pdf"

    def test_unknown_returns_none(self):
        assert QQChannel._make_content_part("xyz", "/tmp/x", "x") is None


# ===================================================================
# send (async)
# ===================================================================


class TestSend:
    async def test_disabled_channel_noop(self):
        ch = _make_channel(enabled=False)
        ch._dispatch_text = AsyncMock()
        await ch.send("user1", "hello")
        ch._dispatch_text.assert_not_called()

    async def test_empty_text_noop(self):
        ch = _make_channel()
        ch._dispatch_text = AsyncMock()
        await ch.send("user1", "   ")
        ch._dispatch_text.assert_not_called()

    async def test_to_handle_group_prefix(self):
        ch = _make_channel()
        ch._get_access_token_async = AsyncMock(return_value="tok")
        ch._send_text_with_fallback = AsyncMock(return_value=True)
        ch._send_images = AsyncMock()
        await ch.send("group:grp_123", "hello")
        call_args = ch._send_text_with_fallback.call_args
        assert call_args[0][0] == "group"  # message_type
        assert call_args[0][3] == "grp_123"  # group_openid

    async def test_to_handle_channel_prefix(self):
        ch = _make_channel()
        ch._get_access_token_async = AsyncMock(return_value="tok")
        ch._send_text_with_fallback = AsyncMock(return_value=True)
        ch._send_images = AsyncMock()
        await ch.send("channel:ch_456", "hello")
        call_args = ch._send_text_with_fallback.call_args
        assert call_args[0][0] == "guild"  # message_type
        assert call_args[0][2] == "ch_456"  # channel_id

    async def test_image_tags_extracted(self):
        ch = _make_channel()
        ch._get_access_token_async = AsyncMock(return_value="tok")
        ch._send_text_with_fallback = AsyncMock(return_value=True)
        ch._send_images = AsyncMock()
        text = "Look: [Image: https://img.example.com/a.png] nice"
        await ch.send("user1", text, {"message_type": "c2c"})
        # text sent without image tag
        sent_text = ch._send_text_with_fallback.call_args[0][4]
        assert "[Image:" not in sent_text
        assert "nice" in sent_text
        # images sent separately
        img_urls = ch._send_images.call_args[0][0]
        assert "https://img.example.com/a.png" in img_urls

    async def test_token_failure_handled(self):
        ch = _make_channel()
        ch._get_access_token_async = AsyncMock(
            side_effect=RuntimeError("no token"),
        )
        ch._send_text_with_fallback = AsyncMock()
        # should not raise
        await ch.send("user1", "hello", {"message_type": "c2c"})
        ch._send_text_with_fallback.assert_not_called()


# ===================================================================
# _send_text_with_fallback
# ===================================================================


class TestSendTextWithFallback:
    async def test_success(self):
        ch = _make_channel()
        ch._dispatch_text = AsyncMock()
        result = await ch._send_text_with_fallback(
            "c2c",
            "u1",
            None,
            None,
            "hello",
            "m1",
            "tok",
            False,
        )
        assert result is True
        ch._dispatch_text.assert_called_once()

    async def test_markdown_fallback_on_validation_error(self):
        ch = _make_channel()
        calls: list = []

        async def fake_dispatch(*args, **kwargs):
            calls.append((args, kwargs))
            if len(calls) == 1:
                raise QQApiError("/test", 400, {"error": "markdown"})

        ch._dispatch_text = fake_dispatch
        result = await ch._send_text_with_fallback(
            "c2c",
            "u1",
            None,
            None,
            "hello https://example.com",
            "m1",
            "tok",
            True,
        )
        assert result is True
        assert len(calls) == 2
        # second call should be plaintext (markdown=False)
        assert (
            calls[1][1].get("markdown") is not True or calls[1][0][-1] is False
        )

    async def test_no_fallback_on_non_markdown_error(self):
        ch = _make_channel()
        ch._dispatch_text = AsyncMock(
            side_effect=QQApiError("/test", 400, {"error": "rate limit"}),
        )
        result = await ch._send_text_with_fallback(
            "c2c",
            "u1",
            None,
            None,
            "hello",
            "m1",
            "tok",
            True,
        )
        assert result is False
        # called only once, no fallback
        assert ch._dispatch_text.call_count == 1

    async def test_plain_text_failure(self):
        ch = _make_channel()
        ch._dispatch_text = AsyncMock(
            side_effect=RuntimeError("network error"),
        )
        result = await ch._send_text_with_fallback(
            "c2c",
            "u1",
            None,
            None,
            "hello",
            "m1",
            "tok",
            False,
        )
        assert result is False


# ===================================================================
# _send_images
# ===================================================================


class TestSendImages:
    async def test_no_images_noop(self):
        ch = _make_channel()
        await ch._send_images([], "c2c", "u1", "m1", "tok", True)
        # no exception

    async def test_unsupported_type_noop(self):
        ch = _make_channel()
        await ch._send_images(
            ["https://img.com/a.png"],
            "guild",
            "u1",
            "m1",
            "tok",
            True,
        )
        # guild not supported, no exception

    @patch(
        "copaw.app.channels.qq.channel._upload_media_async",
        new_callable=AsyncMock,
    )
    @patch(
        "copaw.app.channels.qq.channel._send_media_message_async",
        new_callable=AsyncMock,
    )
    async def test_upload_and_send(self, mock_send_media, mock_upload):
        mock_upload.return_value = "file_info_123"
        ch = _make_channel()
        await ch._send_images(
            ["https://img.com/a.png"],
            "c2c",
            "u1",
            "m1",
            "tok",
            False,
        )
        mock_upload.assert_called_once()
        mock_send_media.assert_called_once()

    @patch(
        "copaw.app.channels.qq.channel._upload_media_async",
        new_callable=AsyncMock,
    )
    async def test_upload_failure_skips(self, mock_upload):
        mock_upload.return_value = None
        ch = _make_channel()
        # should not raise
        await ch._send_images(
            ["https://img.com/a.png"],
            "c2c",
            "u1",
            "m1",
            "tok",
            False,
        )


# ===================================================================
# _send_message_async
# ===================================================================


class TestSendMessageAsync:
    @patch(
        "copaw.app.channels.qq.channel._api_request_async",
        new_callable=AsyncMock,
    )
    async def test_plain_text(self, mock_api):
        mock_api.return_value = {}
        await _send_message_async(
            MagicMock(),
            "tok",
            "/v2/users/u1/messages",
            "hello",
            msg_id="m1",
            use_markdown=False,
            use_msg_seq=True,
            seq_key="c2c",
        )
        mock_api.assert_called_once()
        body = mock_api.call_args[0][4]
        assert body["content"] == "hello"
        assert body["msg_type"] == 0
        assert "msg_seq" in body
        assert body["msg_id"] == "m1"

    @patch(
        "copaw.app.channels.qq.channel._api_request_async",
        new_callable=AsyncMock,
    )
    async def test_markdown(self, mock_api):
        mock_api.return_value = {}
        await _send_message_async(
            MagicMock(),
            "tok",
            "/v2/users/u1/messages",
            "# Title",
            msg_id=None,
            use_markdown=True,
            use_msg_seq=True,
            seq_key="c2c",
        )
        body = mock_api.call_args[0][4]
        assert body["markdown"]["content"] == "# Title"
        assert body["msg_type"] == 2

    @patch(
        "copaw.app.channels.qq.channel._api_request_async",
        new_callable=AsyncMock,
    )
    async def test_channel_no_msg_seq(self, mock_api):
        mock_api.return_value = {}
        await _send_message_async(
            MagicMock(),
            "tok",
            "/channels/ch1/messages",
            "hello",
            use_msg_seq=False,
        )
        body = mock_api.call_args[0][4]
        assert "msg_seq" not in body
        assert "msg_type" not in body


# ===================================================================
# build_agent_request_from_native
# ===================================================================


class TestBuildAgentRequestFromNative:
    def test_basic_request(self):
        ch = _make_channel()
        native = {
            "channel_id": "qq",
            "sender_id": "user_1",
            "content_parts": [
                TextContent(type="text", text="hello"),
            ],
            "meta": {"message_type": "c2c"},
        }
        req = ch.build_agent_request_from_native(native)
        assert req.user_id == "user_1"

    def test_non_dict_payload(self):
        ch = _make_channel()
        req = ch.build_agent_request_from_native("invalid")
        # should not raise, uses empty defaults
        assert req is not None

    def test_with_attachments(self):
        ch = _make_channel()
        ch._parse_qq_attachments = MagicMock(return_value=[])
        native = {
            "channel_id": "qq",
            "sender_id": "user_1",
            "content_parts": [],
            "meta": {
                "attachments": [{"url": "http://a.jpg", "filename": "a.jpg"}],
            },
        }
        ch.build_agent_request_from_native(native)
        ch._parse_qq_attachments.assert_called_once()


# ===================================================================
# start / stop lifecycle
# ===================================================================


class TestLifecycle:
    async def test_start_disabled(self):
        ch = _make_channel(enabled=False)
        await ch.start()
        assert ch._ws_thread is None

    async def test_start_missing_credentials(self):
        ch = _make_channel(app_id="", client_secret="")
        with pytest.raises(RuntimeError, match="QQ_APP_ID"):
            await ch.start()

    async def test_stop_disabled_noop(self):
        ch = _make_channel(enabled=False)
        await ch.stop()  # should not raise
