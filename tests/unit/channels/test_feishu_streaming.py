# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,unused-argument
"""Unit tests for Feishu channel streaming card output."""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from copaw.app.channels.feishu.channel import (
    FeishuChannel,
    _STREAMING_ELEMENT_ID,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _noop_process(_request: Any):
    yield  # pragma: no cover


def _make_channel(**overrides: Any) -> FeishuChannel:
    """Create a FeishuChannel with dummy process handler."""
    defaults = {
        "process": _noop_process,
        "enabled": True,
        "app_id": "test_app_id",
        "app_secret": "test_secret",
        "bot_prefix": "",
    }
    defaults.update(overrides)
    ch = FeishuChannel(**defaults)
    ch._http_client = MagicMock()
    return ch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_http():
    """Mock httpx.AsyncClient instance."""
    client = AsyncMock()
    client.post = AsyncMock()
    client.put = AsyncMock()
    client.patch = AsyncMock()
    return client


@pytest.fixture
def channel(mock_http):
    """Create a FeishuChannel instance with mocked internals."""
    ch = _make_channel()
    ch._http_client = mock_http
    ch._stream_seq = 0
    ch.domain = "feishu"
    return ch


def _ok_feishu(data=None):
    """Build a mock 200 response with feishu success code."""
    resp = MagicMock()
    resp.status_code = 200
    body = {"code": 0}
    if data:
        body["data"] = data
    resp.json.return_value = body
    return resp


def _fail_http(status=400, text="Bad Request"):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    return resp


def _fail_feishu(code=99999, msg="error"):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"code": code, "msg": msg}
    return resp


# ---------------------------------------------------------------------------
# _is_streaming_enabled
# ---------------------------------------------------------------------------


class TestIsStreamingEnabled:
    def test_true_values(self, channel, monkeypatch):
        for val in ("true", "True", "TRUE", "1", "yes"):
            monkeypatch.setenv("FEISHU_STREAMING_ENABLED", val)
            assert channel._is_streaming_enabled() is True

    def test_false_values(self, channel, monkeypatch):
        for val in ("false", "0", "no", "", "random"):
            monkeypatch.setenv("FEISHU_STREAMING_ENABLED", val)
            assert channel._is_streaming_enabled() is False

    def test_unset(self, channel, monkeypatch):
        monkeypatch.delenv("FEISHU_STREAMING_ENABLED", raising=False)
        assert channel._is_streaming_enabled() is False


# ---------------------------------------------------------------------------
# _next_stream_seq
# ---------------------------------------------------------------------------


class TestNextStreamSeq:
    def test_monotonic(self, channel):
        assert channel._next_stream_seq() == 1
        assert channel._next_stream_seq() == 2
        assert channel._next_stream_seq() == 3

    def test_starts_at_1(self, channel):
        channel._stream_seq = 0
        assert channel._next_stream_seq() == 1


# ---------------------------------------------------------------------------
# _feishu_base_url
# ---------------------------------------------------------------------------


class TestFeishuBaseUrl:
    def test_feishu_domain(self, channel):
        channel.domain = "feishu"
        assert channel._feishu_base_url() == "https://open.feishu.cn"

    def test_lark_domain(self, channel):
        channel.domain = "lark"
        assert channel._feishu_base_url() == "https://open.larksuite.com"


# ---------------------------------------------------------------------------
# _card_create
# ---------------------------------------------------------------------------


class TestCardCreate:
    @pytest.mark.asyncio
    async def test_success(self, channel, mock_http):
        mock_http.post.return_value = _ok_feishu({"card_id": "card_abc123"})
        channel._streaming_auth_headers = MagicMock(
            return_value={"Authorization": "Bearer t"},
        )

        result = await channel._card_create()

        assert result == "card_abc123"
        mock_http.post.assert_awaited_once()
        call_url = mock_http.post.call_args[0][0]
        assert "cardkit/v1/cards" in call_url

    @pytest.mark.asyncio
    async def test_http_failure(self, channel, mock_http):
        mock_http.post.return_value = _fail_http()
        channel._streaming_auth_headers = MagicMock(
            return_value={"Authorization": "Bearer t"},
        )

        result = await channel._card_create()

        assert result is None

    @pytest.mark.asyncio
    async def test_feishu_error_code(self, channel, mock_http):
        mock_http.post.return_value = _fail_feishu()
        channel._streaming_auth_headers = MagicMock(
            return_value={"Authorization": "Bearer t"},
        )

        result = await channel._card_create()

        assert result is None

    @pytest.mark.asyncio
    async def test_sends_cardkit_schema(self, channel, mock_http):
        mock_http.post.return_value = _ok_feishu({"card_id": "card_x"})
        channel._streaming_auth_headers = MagicMock(
            return_value={"Authorization": "Bearer t"},
        )

        await channel._card_create()

        call_kwargs = mock_http.post.call_args[1]
        body = call_kwargs["json"]
        assert body["type"] == "card_json"
        card = json.loads(body["data"])
        assert card["schema"] == "2.0"
        assert card["config"]["streaming_mode"] is True
        assert (
            card["config"]["streaming_config"]["print_frequency_ms"]["default"]
            == 50
        )
        content_els = [
            e
            for e in card["body"]["elements"]
            if e["element_id"] == _STREAMING_ELEMENT_ID
        ]
        assert len(content_els) == 1
        assert content_els[0]["tag"] == "markdown"


# ---------------------------------------------------------------------------
# _card_send
# ---------------------------------------------------------------------------


class TestCardSend:
    @pytest.mark.asyncio
    async def test_success(self, channel, mock_http):
        mock_http.post.return_value = _ok_feishu({"message_id": "msg_456"})
        channel._streaming_auth_headers = MagicMock(
            return_value={"Authorization": "Bearer t"},
        )

        result = await channel._card_send("card_123", "ou_test", "open_id")

        assert result == "msg_456"

    @pytest.mark.asyncio
    async def test_http_failure(self, channel, mock_http):
        mock_http.post.return_value = _fail_http()
        channel._streaming_auth_headers = MagicMock(
            return_value={"Authorization": "Bearer t"},
        )

        result = await channel._card_send("card_123", "ou_test", "open_id")

        assert result is None


# ---------------------------------------------------------------------------
# _card_update_text
# ---------------------------------------------------------------------------


class TestCardUpdateText:
    @pytest.mark.asyncio
    async def test_success(self, channel, mock_http):
        mock_http.put.return_value = _ok_feishu()
        channel._streaming_auth_headers = MagicMock(
            return_value={"Authorization": "Bearer t"},
        )

        result = await channel._card_update_text("card_123", "Hello world")

        assert result is True
        mock_http.put.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_http_failure(self, channel, mock_http):
        mock_http.put.return_value = _fail_http()
        channel._streaming_auth_headers = MagicMock(
            return_value={"Authorization": "Bearer t"},
        )

        result = await channel._card_update_text("card_123", "Hello")

        assert result is False

    @pytest.mark.asyncio
    async def test_feishu_error_code(self, channel, mock_http):
        mock_http.put.return_value = _fail_feishu()
        channel._streaming_auth_headers = MagicMock(
            return_value={"Authorization": "Bearer t"},
        )

        result = await channel._card_update_text("card_123", "Hello")

        assert result is False

    @pytest.mark.asyncio
    async def test_sends_full_text(self, channel, mock_http):
        mock_http.put.return_value = _ok_feishu()
        channel._streaming_auth_headers = MagicMock(
            return_value={"Authorization": "Bearer t"},
        )

        await channel._card_update_text("card_123", "full text here")

        call_kwargs = mock_http.put.call_args[1]
        body = call_kwargs["json"]
        assert body["content"] == "full text here"
        assert body["sequence"] >= 1

    @pytest.mark.asyncio
    async def test_url_contains_card_id_and_element(self, channel, mock_http):
        mock_http.put.return_value = _ok_feishu()
        channel._streaming_auth_headers = MagicMock(
            return_value={"Authorization": "Bearer t"},
        )

        await channel._card_update_text("card_xyz", "text")

        call_url = mock_http.put.call_args[0][0]
        assert "card_xyz" in call_url
        assert f"elements/{_STREAMING_ELEMENT_ID}/content" in call_url


# ---------------------------------------------------------------------------
# _card_close
# ---------------------------------------------------------------------------


class TestCardClose:
    @pytest.mark.asyncio
    async def test_success(self, channel, mock_http):
        mock_http.patch.return_value = _ok_feishu()
        channel._streaming_auth_headers = MagicMock(
            return_value={"Authorization": "Bearer t"},
        )

        await channel._card_close("card_123")

        mock_http.patch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sends_streaming_mode_false(self, channel, mock_http):
        mock_http.patch.return_value = _ok_feishu()
        channel._streaming_auth_headers = MagicMock(
            return_value={"Authorization": "Bearer t"},
        )

        await channel._card_close("card_123")

        call_kwargs = mock_http.patch.call_args[1]
        body = call_kwargs["json"]
        settings = json.loads(body["settings"])
        assert settings["config"]["streaming_mode"] is False

    @pytest.mark.asyncio
    async def test_http_failure_no_raise(self, channel, mock_http):
        mock_http.patch.return_value = _fail_http(500, "Server Error")
        channel._streaming_auth_headers = MagicMock(
            return_value={"Authorization": "Bearer t"},
        )

        await channel._card_close("card_123")

    @pytest.mark.asyncio
    async def test_exception_no_raise(self, channel, mock_http):
        mock_http.patch.side_effect = Exception("connection reset")
        channel._streaming_auth_headers = MagicMock(
            return_value={"Authorization": "Bearer t"},
        )

        await channel._card_close("card_123")


# ---------------------------------------------------------------------------
# _extract_streaming_text
# ---------------------------------------------------------------------------


class TestExtractStreamingText:
    def test_message_completed(self, channel):
        ev = MagicMock()
        ev.object = "message"
        channel._message_to_content_parts = MagicMock(
            return_value=[
                MagicMock(type="text", text="hello world"),
            ],
        )

        result = channel._extract_streaming_text(ev, is_streaming=False)
        assert result == "hello world"

    def test_delta_attribute(self, channel):
        ev = MagicMock()
        ev.object = "response"
        ev.delta = "partial text"
        ev.content = None
        ev.text = None
        ev.content_part = None

        result = channel._extract_streaming_text(ev, is_streaming=True)
        assert result == "partial text"

    def test_content_attribute(self, channel):
        ev = MagicMock()
        ev.object = "response"
        ev.delta = None
        ev.content = "some content"
        ev.text = None
        ev.content_part = None

        result = channel._extract_streaming_text(ev, is_streaming=True)
        assert result == "some content"

    def test_nested_message(self, channel):
        ev = MagicMock(spec=[])
        inner = MagicMock()
        inner.content = "nested text"
        ev.message = inner

        result = channel._extract_streaming_text(ev, is_streaming=True)
        assert result == "nested text"

    def test_returns_none_when_empty(self, channel):
        ev = MagicMock(spec=[])
        result = channel._extract_streaming_text(ev, is_streaming=False)
        assert result is None


# ---------------------------------------------------------------------------
# _stream_with_tracker routing
# ---------------------------------------------------------------------------


class TestStreamWithTrackerRouting:
    """Verify _stream_with_tracker delegates correctly."""

    @pytest.mark.asyncio
    async def test_disabled_delegates_to_super(self, channel, monkeypatch):
        """When streaming disabled, should delegate to super."""
        monkeypatch.delenv("FEISHU_STREAMING_ENABLED", raising=False)

        async def fake_super(payload):
            yield "data: super_chunk\n\n"

        monkeypatch.setattr(
            type(channel).__bases__[0],
            "_stream_with_tracker",
            fake_super,
        )

        result = []
        async for chunk in channel._stream_with_tracker({"meta": {}}):
            result.append(chunk)

        assert result == ["data: super_chunk\n\n"]

    @pytest.mark.asyncio
    async def test_enabled_yields_sse_events(self, channel, monkeypatch):
        """When streaming enabled, should yield SSE events."""
        monkeypatch.setenv("FEISHU_STREAMING_ENABLED", "true")

        monkeypatch.setattr(
            channel,
            "_payload_to_request",
            lambda p: MagicMock(),
        )
        monkeypatch.setattr(
            channel,
            "get_to_handle_from_request",
            lambda r: "test_user",
        )
        monkeypatch.setattr(channel, "_before_consume_process", AsyncMock())
        monkeypatch.setattr(
            channel,
            "_get_receive_for_send",
            AsyncMock(return_value=("open_id", "ou_123")),
        )
        monkeypatch.setattr(
            channel,
            "_streaming_auth_headers",
            lambda: {"Authorization": "Bearer t"},
        )
        monkeypatch.setattr(channel, "_next_stream_seq", lambda: 1)
        monkeypatch.setattr(
            channel,
            "_feishu_base_url",
            lambda: "https://open.feishu.cn",
        )

        from agentscope_runtime.engine.schemas.agent_schemas import RunStatus

        ev1 = MagicMock()
        ev1.object = "response"
        ev1.status = None
        ev1.model_dump_json = lambda: '{"object":"response"}'

        ev2 = MagicMock()
        ev2.object = "message"
        ev2.status = RunStatus.Completed
        ev2.model_dump_json = lambda: '{"object":"message"}'

        async def fake_process(req):
            yield ev1
            yield ev2

        monkeypatch.setattr(channel, "_process", fake_process)

        content_part = MagicMock()
        content_part.type = "text"
        content_part.text = "Hello"
        monkeypatch.setattr(
            channel,
            "_message_to_content_parts",
            lambda ev: [content_part],
        )
        monkeypatch.setattr(
            channel,
            "send_content_parts",
            AsyncMock(return_value="m1"),
        )
        monkeypatch.setattr(
            channel,
            "_get_response_error_message",
            lambda r: None,
        )
        monkeypatch.setattr(channel, "_add_reaction", AsyncMock())
        monkeypatch.setattr(
            channel,
            "get_on_reply_sent_args",
            lambda r, t: (r, t),
        )
        monkeypatch.setattr(channel, "_on_reply_sent", None)

        chunks = []
        async for chunk in channel._stream_with_tracker({"meta": {}}):
            chunks.append(chunk)

        assert len(chunks) >= 2
        assert "data:" in chunks[0]


class TestStreamWithTrackerStreaming:
    """Test streaming card lifecycle via _stream_with_tracker."""

    @pytest.mark.asyncio
    async def test_card_lifecycle_via_tracker(
        self,
        channel,
        mock_http,
        monkeypatch,
    ):
        """Full lifecycle: create card -> stream -> close via tracker."""
        monkeypatch.setenv("FEISHU_STREAMING_ENABLED", "true")

        monkeypatch.setattr(
            channel,
            "_payload_to_request",
            lambda p: MagicMock(),
        )
        monkeypatch.setattr(
            channel,
            "get_to_handle_from_request",
            lambda r: "test_user",
        )
        monkeypatch.setattr(channel, "_before_consume_process", AsyncMock())
        monkeypatch.setattr(
            channel,
            "_get_receive_for_send",
            AsyncMock(return_value=("open_id", "ou_123")),
        )
        monkeypatch.setattr(
            channel,
            "_streaming_auth_headers",
            lambda: {"Authorization": "Bearer t"},
        )
        monkeypatch.setattr(channel, "_next_stream_seq", lambda: 1)
        monkeypatch.setattr(
            channel,
            "_feishu_base_url",
            lambda: "https://open.feishu.cn",
        )

        mock_http.post.return_value = _ok_feishu(
            data={"card_id": "card_test123"},
        )
        mock_http.put.return_value = _ok_feishu()
        mock_http.patch.return_value = _ok_feishu()

        from agentscope_runtime.engine.schemas.agent_schemas import RunStatus

        async def fake_process(req):
            ev1 = MagicMock()
            ev1.object = "message"
            ev1.status = RunStatus.InProgress
            ev1.model_dump_json = lambda: '{"partial":true}'
            yield ev1

            ev2 = MagicMock()
            ev2.object = "message"
            ev2.status = RunStatus.Completed
            ev2.model_dump_json = lambda: '{"done":true}'
            yield ev2

        monkeypatch.setattr(channel, "_process", fake_process)
        monkeypatch.setattr(
            channel,
            "_extract_streaming_text",
            lambda ev, is_streaming=True: "Hello world",
        )

        content_part = MagicMock()
        content_part.type = "text"
        content_part.text = "Hello world"
        monkeypatch.setattr(
            channel,
            "_message_to_content_parts",
            lambda ev: [content_part],
        )
        monkeypatch.setattr(
            channel,
            "send_content_parts",
            AsyncMock(return_value="m1"),
        )
        monkeypatch.setattr(
            channel,
            "_get_response_error_message",
            lambda r: None,
        )
        monkeypatch.setattr(channel, "_add_reaction", AsyncMock())
        monkeypatch.setattr(
            channel,
            "get_on_reply_sent_args",
            lambda r, t: (r, t),
        )
        monkeypatch.setattr(channel, "_on_reply_sent", None)

        chunks = []
        async for chunk in channel._stream_with_tracker({"meta": {}}):
            chunks.append(chunk)

        assert mock_http.post.await_count >= 1
        assert mock_http.patch.await_count >= 1
        assert len(chunks) >= 2

    @pytest.mark.asyncio
    async def test_fallback_on_card_failure_via_tracker(
        self,
        channel,
        mock_http,
        monkeypatch,
    ):
        """Card creation fails -> fall back to normal send via tracker."""
        monkeypatch.setenv("FEISHU_STREAMING_ENABLED", "true")

        monkeypatch.setattr(
            channel,
            "_payload_to_request",
            lambda p: MagicMock(),
        )
        monkeypatch.setattr(
            channel,
            "get_to_handle_from_request",
            lambda r: "test_user",
        )
        monkeypatch.setattr(channel, "_before_consume_process", AsyncMock())
        monkeypatch.setattr(
            channel,
            "_get_receive_for_send",
            AsyncMock(return_value=("open_id", "ou_123")),
        )
        monkeypatch.setattr(
            channel,
            "_streaming_auth_headers",
            lambda: {"Authorization": "Bearer t"},
        )
        monkeypatch.setattr(channel, "_next_stream_seq", lambda: 1)
        monkeypatch.setattr(
            channel,
            "_feishu_base_url",
            lambda: "https://open.feishu.cn",
        )

        mock_http.post.return_value = _fail_http(500, "Server Error")
        mock_http.patch.return_value = _ok_feishu()

        from agentscope_runtime.engine.schemas.agent_schemas import RunStatus

        async def fake_process(req):
            ev = MagicMock()
            ev.object = "message"
            ev.status = RunStatus.Completed
            ev.model_dump_json = lambda: '{"done":true}'
            yield ev

        monkeypatch.setattr(channel, "_process", fake_process)

        content_part = MagicMock()
        content_part.type = "text"
        content_part.text = "Hello"
        monkeypatch.setattr(
            channel,
            "_message_to_content_parts",
            lambda ev: [content_part],
        )
        monkeypatch.setattr(
            channel,
            "send_content_parts",
            AsyncMock(return_value="m_fallback"),
        )
        monkeypatch.setattr(
            channel,
            "_get_response_error_message",
            lambda r: None,
        )
        monkeypatch.setattr(channel, "_add_reaction", AsyncMock())
        monkeypatch.setattr(
            channel,
            "get_on_reply_sent_args",
            lambda r, t: (r, t),
        )
        monkeypatch.setattr(channel, "_on_reply_sent", None)

        async for _ in channel._stream_with_tracker({"meta": {}}):
            pass

        channel.send_content_parts.assert_awaited()
