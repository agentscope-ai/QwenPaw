# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,unused-argument
"""Unit tests for Feishu channel streaming card output."""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

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
# _run_process_loop routing
# ---------------------------------------------------------------------------


class TestProcessLoopRouting:
    @pytest.mark.asyncio
    async def test_disabled_stays_normal(self, channel, monkeypatch):
        monkeypatch.setenv("FEISHU_STREAMING_ENABLED", "false")
        with patch.object(
            FeishuChannel,
            "_run_process_loop_streaming",
            new_callable=AsyncMock,
        ) as mock_streaming:
            await channel._run_process_loop(
                request=MagicMock(),
                to_handle="test",
                send_meta={},
            )
            mock_streaming.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_enabled_calls_streaming(self, channel, monkeypatch):
        monkeypatch.setenv("FEISHU_STREAMING_ENABLED", "true")
        with patch.object(
            FeishuChannel,
            "_run_process_loop_streaming",
            new_callable=AsyncMock,
        ) as mock_streaming:
            await channel._run_process_loop(
                request=MagicMock(),
                to_handle="test",
                send_meta={},
            )
            mock_streaming.assert_awaited_once()


# ---------------------------------------------------------------------------
# _run_process_loop_streaming integration
# ---------------------------------------------------------------------------


class TestProcessLoopStreaming:
    """Integration tests for _run_process_loop_streaming core flow.

    Tests the interaction between the main event loop and the background
    updater task, state transitions (card creation, updates, closing),
    and fallback mechanisms on API failure.
    """

    @pytest.mark.asyncio
    async def test_card_create_send_close_lifecycle(self, channel, mock_http, monkeypatch):
        """Full lifecycle: _card_create → _card_send → updater → _card_close."""
        monkeypatch.setattr(channel, "_streaming_auth_headers",
                            lambda: {"Authorization": "Bearer t"})
        monkeypatch.setattr(channel, "_get_receive_for_send",
                            AsyncMock(return_value=("open_id", "ou_123")))
        monkeypatch.setattr(channel, "_next_stream_seq", lambda: 1)
        monkeypatch.setattr(channel, "_feishu_base_url",
                            lambda: "https://open.feishu.cn")

        # _card_create → success
        mock_http.post.return_value = _ok_feishu(data={"card_id": "c1"})
        # _card_send → success
        mock_http.put.return_value = _ok_feishu(data={"message_id": "m1"})
        # _card_update_text + _card_close → success
        mock_http.patch.return_value = _ok_feishu()

        monkeypatch.setattr(channel, "_card_update_text",
                            AsyncMock(return_value=True))

        from agentscope_runtime.engine.schemas.agent_schemas import RunStatus

        async def fake_process(req):
            # InProgress event with text
            ev1 = MagicMock()
            ev1.object = "response.delta"
            ev1.status = RunStatus.InProgress
            yield ev1

            # Completed event
            ev2 = MagicMock()
            ev2.object = "message"
            ev2.status = RunStatus.Completed
            yield ev2

        # _extract_streaming_text: always return text for InProgress, final for Completed
        def fake_extract(ev, is_streaming=True):
            if not is_streaming:
                return "Hello world"
            return "Hello world"

        monkeypatch.setattr(channel, "_process", fake_process)
        monkeypatch.setattr(channel, "_extract_streaming_text", fake_extract)

        # Mock _message_to_content_parts for Completed fallback
        content_part = MagicMock()
        content_part.type = "text"
        content_part.text = "Hello world"
        monkeypatch.setattr(channel, "_message_to_content_parts",
                            lambda ev: [content_part])
        monkeypatch.setattr(channel, "send_content_parts",
                            AsyncMock(return_value="m_normal"))

        monkeypatch.setattr(channel, "_get_response_error_message",
                            lambda r: None)
        monkeypatch.setattr(channel, "_add_reaction", AsyncMock())
        monkeypatch.setattr(channel, "get_on_reply_sent_args",
                            lambda r, t: (r, t))
        monkeypatch.setattr(channel, "_on_reply_sent", None)

        await channel._run_process_loop_streaming(
            request=MagicMock(),
            to_handle="test_user",
            send_meta={},
        )

        # Card should have been created (POST to cardkit)
        assert mock_http.post.await_count >= 1

    @pytest.mark.asyncio
    async def test_card_create_falls_back_on_failure(self, channel, mock_http, monkeypatch):
        """Card creation fails → should fall back to normal send."""
        monkeypatch.setattr(channel, "_streaming_auth_headers",
                            lambda: {"Authorization": "Bearer t"})
        monkeypatch.setattr(channel, "_get_receive_for_send",
                            AsyncMock(return_value=("open_id", "ou_123")))
        monkeypatch.setattr(channel, "_next_stream_seq", lambda: 1)
        monkeypatch.setattr(channel, "_feishu_base_url",
                            lambda: "https://open.feishu.cn")

        # Card create fails
        mock_http.post.return_value = _fail_http(500, "Internal Server Error")
        mock_http.patch.return_value = _ok_feishu()
        mock_http.put.return_value = _ok_feishu(data={"message_id": "m1"})

        monkeypatch.setattr(channel, "_card_update_text",
                            AsyncMock(return_value=True))

        from agentscope_runtime.engine.schemas.agent_schemas import RunStatus

        async def fake_process(req):
            ev1 = MagicMock()
            ev1.object = "response.delta"
            ev1.status = RunStatus.InProgress
            yield ev1

            ev2 = MagicMock()
            ev2.object = "message"
            ev2.status = RunStatus.Completed
            yield ev2

        def fake_extract(ev, is_streaming=True):
            return "Hello"

        monkeypatch.setattr(channel, "_process", fake_process)
        monkeypatch.setattr(channel, "_extract_streaming_text", fake_extract)

        content_part = MagicMock()
        content_part.type = "text"
        content_part.text = "Hello"
        monkeypatch.setattr(channel, "_message_to_content_parts",
                            lambda ev: [content_part])
        monkeypatch.setattr(channel, "send_content_parts",
                            AsyncMock(return_value="m_fallback"))

        monkeypatch.setattr(channel, "_get_response_error_message",
                            lambda r: None)
        monkeypatch.setattr(channel, "_add_reaction", AsyncMock())
        monkeypatch.setattr(channel, "get_on_reply_sent_args",
                            lambda r, t: (r, t))
        monkeypatch.setattr(channel, "_on_reply_sent", None)

        await channel._run_process_loop_streaming(
            request=MagicMock(),
            to_handle="test_user",
            send_meta={},
        )

        # Should have fallen back to send_content_parts
        channel.send_content_parts.assert_awaited()

