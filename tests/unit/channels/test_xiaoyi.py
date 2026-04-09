# -*- coding: utf-8 -*-
"""
XiaoYi Channel Unit Tests

Generated using python-test-pattern skill v0.2.0
Tests cover: initialization, factory methods, lifecycle, message handling,
WebSocket operations

Run:
    pytest tests/unit/channels/test_xiaoyi.py -v
"""
# pylint: disable=redefined-outer-name,protected-access,unused-argument
from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, Mock, patch, call

import pytest
import aiohttp
from aiohttp import WSMsgType


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_process():
    """Create mock process handler."""

    async def mock_handler(*_args, **_kwargs):
        mock_event = MagicMock()
        mock_event.object = "message"
        mock_event.status = "completed"
        mock_event.type = "text"
        yield mock_event

    return AsyncMock(side_effect=mock_handler)


@pytest.fixture
def mock_ws():
    """Create mock WebSocket connection."""
    ws = MagicMock()
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    return ws


@pytest.fixture
def mock_session(mock_ws):
    """Create mock aiohttp ClientSession with WebSocket."""
    session = MagicMock()
    session.ws_connect = AsyncMock(return_value=mock_ws)
    session.close = AsyncMock()
    return session


@pytest.fixture
def xiaoyi_channel(mock_process, tmp_path):
    """Create XiaoYiChannel instance for testing."""
    from copaw.app.channels.xiaoyi.channel import XiaoYiChannel

    channel = XiaoYiChannel(
        process=mock_process,
        enabled=True,
        ak="test_ak_123456",
        sk="test_sk_abcdef",
        agent_id="test_agent_123",
        ws_url="wss://test.example.com/ws",
        task_timeout_ms=3600000,
        bot_prefix="[小艺] ",
        media_dir=str(tmp_path / "media"),
    )
    return channel


@pytest.fixture
def mock_auth_headers():
    """Mock authentication headers."""
    return {
        "x-access-key": "test_ak_123456",
        "x-sign": "mock_signature",
        "x-ts": "1234567890",
        "x-agent-id": "test_agent_123",
    }


# =============================================================================
# P0: Initialization Tests
# =============================================================================


@pytest.mark.asyncio
class TestXiaoYiChannelInit:
    """
    P0: XiaoYiChannel initialization tests.
    """

    def test_init_stores_basic_config(self, mock_process, tmp_path):
        """Constructor should store all basic configuration parameters."""
        from copaw.app.channels.xiaoyi.channel import XiaoYiChannel

        channel = XiaoYiChannel(
            process=mock_process,
            enabled=True,
            ak="test_ak",
            sk="test_sk",
            agent_id="test_agent",
            ws_url="wss://test.example.com/ws",
            task_timeout_ms=5000,
            bot_prefix="[Test] ",
            media_dir=str(tmp_path / "media"),
        )

        assert channel.enabled is True
        assert channel.ak == "test_ak"
        assert channel.sk == "test_sk"
        assert channel.agent_id == "test_agent"
        assert channel.ws_url == "wss://test.example.com/ws"
        assert channel.task_timeout_ms == 5000
        assert channel.bot_prefix == "[Test] "
        assert channel._media_dir == tmp_path / "media"

    def test_init_creates_required_data_structures(
        self,
        mock_process,
        tmp_path,
    ):
        """Constructor should initialize internal data structures."""
        from copaw.app.channels.xiaoyi.channel import XiaoYiChannel

        channel = XiaoYiChannel(
            process=mock_process,
            enabled=True,
            ak="test_ak",
            sk="test_sk",
            agent_id="test_agent",
            ws_url="wss://test.example.com/ws",
        )

        assert hasattr(channel, "_session_task_map")
        assert isinstance(channel._session_task_map, dict)
        assert channel._ws is None
        assert channel._session is None
        assert channel._connected is False
        assert channel._reconnect_attempts == 0

    def test_init_with_workspace_dir(self, mock_process, tmp_path):
        """Constructor should use workspace-specific media dir when provided."""
        from copaw.app.channels.xiaoyi.channel import XiaoYiChannel

        workspace = tmp_path / "workspace"
        channel = XiaoYiChannel(
            process=mock_process,
            enabled=True,
            ak="test_ak",
            sk="test_sk",
            agent_id="test_agent",
            ws_url="wss://test.example.com/ws",
            workspace_dir=workspace,
        )

        assert channel._media_dir == workspace / "media"


# =============================================================================
# P0: Factory Method Tests
# =============================================================================


@pytest.mark.asyncio
class TestXiaoYiChannelFactoryMethods:
    """
    P0: Factory method tests - from_env and from_config.
    """

    def test_from_env_reads_env_vars(self, monkeypatch, mock_process):
        """from_env should correctly read environment variables."""
        from copaw.app.channels.xiaoyi.channel import XiaoYiChannel

        monkeypatch.setenv("XIAOYI_CHANNEL_ENABLED", "1")
        monkeypatch.setenv("XIAOYI_AK", "env_ak_value")
        monkeypatch.setenv("XIAOYI_SK", "env_sk_value")
        monkeypatch.setenv("XIAOYI_AGENT_ID", "env_agent_123")
        monkeypatch.setenv("XIAOYI_WS_URL", "wss://env.example.com/ws")
        monkeypatch.setenv("XIAOYI_MEDIA_DIR", "/env/media")

        channel = XiaoYiChannel.from_env(process=mock_process)

        assert channel.enabled is True
        assert channel.ak == "env_ak_value"
        assert channel.sk == "env_sk_value"
        assert channel.agent_id == "env_agent_123"
        assert channel.ws_url == "wss://env.example.com/ws"

    def test_from_env_uses_defaults(self, monkeypatch, mock_process):
        """from_env should use default values when environment variables are missing."""
        from copaw.app.channels.xiaoyi.channel import XiaoYiChannel

        monkeypatch.delenv("XIAOYI_CHANNEL_ENABLED", raising=False)
        monkeypatch.delenv("XIAOYI_AK", raising=False)
        monkeypatch.delenv("XIAOYI_SK", raising=False)
        monkeypatch.delenv("XIAOYI_AGENT_ID", raising=False)
        monkeypatch.delenv("XIAOYI_WS_URL", raising=False)

        channel = XiaoYiChannel.from_env(process=mock_process)

        assert channel.enabled is False
        assert channel.ak == ""
        assert channel.sk == ""
        assert channel.agent_id == ""
        assert (
            channel.ws_url == "wss://hag.cloud.huawei.com/openclaw/v1/ws/link"
        )

    def test_from_config_with_object(self, mock_process):
        """from_config should use config object values."""
        from copaw.app.channels.xiaoyi.channel import XiaoYiChannel

        config = Mock()
        config.enabled = True
        config.ak = "config_ak"
        config.sk = "config_sk"
        config.agent_id = "config_agent"
        config.ws_url = "wss://config.example.com/ws"
        config.task_timeout_ms = 60000
        config.bot_prefix = "[Config] "
        config.media_dir = "/config/media"

        channel = XiaoYiChannel.from_config(
            process=mock_process,
            config=config,
        )

        assert channel.enabled is True
        assert channel.ak == "config_ak"
        assert channel.sk == "config_sk"
        assert channel.agent_id == "config_agent"
        assert channel.task_timeout_ms == 60000
        assert channel.bot_prefix == "[Config] "

    def test_from_config_with_dict(self, mock_process):
        """from_config should work with dict config."""
        from copaw.app.channels.xiaoyi.channel import XiaoYiChannel

        config = {
            "enabled": True,
            "ak": "dict_ak",
            "sk": "dict_sk",
            "agent_id": "dict_agent",
            "ws_url": "wss://dict.example.com/ws",
            "task_timeout_ms": 30000,
            "bot_prefix": "[Dict] ",
        }

        channel = XiaoYiChannel.from_config(
            process=mock_process,
            config=config,
        )

        assert channel.enabled is True
        assert channel.ak == "dict_ak"
        assert channel.sk == "dict_sk"
        assert channel.agent_id == "dict_agent"
        assert channel.ws_url == "wss://dict.example.com/ws"


# =============================================================================
# P0: Configuration Validation Tests
# =============================================================================


@pytest.mark.asyncio
class TestXiaoYiChannelValidation:
    """
    P0: Configuration validation tests.
    """

    def test_validate_config_raises_on_missing_ak(self, mock_process):
        """_validate_config should raise ValueError when AK is missing."""
        from copaw.app.channels.xiaoyi.channel import XiaoYiChannel

        channel = XiaoYiChannel(
            process=mock_process,
            enabled=True,
            ak="",
            sk="test_sk",
            agent_id="test_agent",
            ws_url="wss://test.example.com/ws",
        )

        with pytest.raises(ValueError, match="AK"):
            channel._validate_config()

    def test_validate_config_raises_on_missing_sk(self, mock_process):
        """_validate_config should raise ValueError when SK is missing."""
        from copaw.app.channels.xiaoyi.channel import XiaoYiChannel

        channel = XiaoYiChannel(
            process=mock_process,
            enabled=True,
            ak="test_ak",
            sk="",
            agent_id="test_agent",
            ws_url="wss://test.example.com/ws",
        )

        with pytest.raises(ValueError, match="SK"):
            channel._validate_config()

    def test_validate_config_raises_on_missing_agent_id(self, mock_process):
        """_validate_config should raise ValueError when agent_id is missing."""
        from copaw.app.channels.xiaoyi.channel import XiaoYiChannel

        channel = XiaoYiChannel(
            process=mock_process,
            enabled=True,
            ak="test_ak",
            sk="test_sk",
            agent_id="",
            ws_url="wss://test.example.com/ws",
        )

        with pytest.raises(ValueError, match="Agent ID"):
            channel._validate_config()


# =============================================================================
# P0/P1: Lifecycle Tests (Start/Stop)
# =============================================================================


@pytest.mark.asyncio
class TestXiaoYiChannelLifecycle:
    """
    P0/P1: Lifecycle tests for start/stop operations.
    """

    async def test_start_skips_when_disabled(self, xiaoyi_channel):
        """start() should do nothing when channel is disabled."""
        xiaoyi_channel.enabled = False

        with patch.object(xiaoyi_channel, "_validate_config") as mock_validate:
            await xiaoyi_channel.start()
            mock_validate.assert_not_called()

    async def test_start_validates_config(self, xiaoyi_channel):
        """start() should validate config before connecting."""
        xiaoyi_channel.enabled = True

        with patch.object(xiaoyi_channel, "_validate_config") as mock_validate:
            with patch.object(
                xiaoyi_channel,
                "_wait_and_register_connection",
                new_callable=AsyncMock,
            ):
                with patch("aiohttp.ClientSession") as MockSession:
                    mock_session = MockSession.return_value
                    mock_session.ws_connect = AsyncMock()
                    await xiaoyi_channel.start()
                    mock_validate.assert_called_once()

    async def test_start_handles_validation_error(self, xiaoyi_channel):
        """start() should handle config validation errors gracefully."""
        xiaoyi_channel.enabled = True
        xiaoyi_channel.ak = ""  # Invalid config

        await xiaoyi_channel.start()

        assert xiaoyi_channel._connected is False

    async def test_stop_cleans_up_resources(self, xiaoyi_channel, mock_ws):
        """stop() should clean up all resources."""
        xiaoyi_channel._ws = mock_ws
        xiaoyi_channel._session = MagicMock()
        xiaoyi_channel._session.close = AsyncMock()
        xiaoyi_channel._connected = True
        xiaoyi_channel._heartbeat_task = None
        xiaoyi_channel._receive_task = None

        await xiaoyi_channel.stop()

        assert xiaoyi_channel._connected is False
        assert xiaoyi_channel._stopping is True
        mock_ws.close.assert_called_once()

    async def test_stop_handles_missing_ws(self, xiaoyi_channel):
        """stop() should handle missing WebSocket gracefully."""
        xiaoyi_channel._ws = None
        xiaoyi_channel._session = None
        xiaoyi_channel._connected = True

        await xiaoyi_channel.stop()

        assert xiaoyi_channel._connected is False

    async def test_stop_cancels_tasks(self, xiaoyi_channel, mock_ws):
        """stop() should cancel running tasks."""
        xiaoyi_channel._ws = mock_ws
        xiaoyi_channel._session = MagicMock()
        xiaoyi_channel._session.close = AsyncMock()
        xiaoyi_channel._connected = True

        # Create mock tasks
        mock_heartbeat = MagicMock()
        mock_heartbeat.cancel = Mock()
        mock_heartbeat.__await__ = Mock(return_value=iter([]))

        mock_receive = MagicMock()
        mock_receive.cancel = Mock()
        mock_receive.__await__ = Mock(return_value=iter([]))

        xiaoyi_channel._heartbeat_task = mock_heartbeat
        xiaoyi_channel._receive_task = mock_receive

        await xiaoyi_channel.stop()

        mock_heartbeat.cancel.assert_called_once()
        mock_receive.cancel.assert_called_once()


# =============================================================================
# P0: WebSocket Connection Tests
# =============================================================================


@pytest.mark.asyncio
class TestXiaoYiChannelWebSocketConnection:
    """
    P0: WebSocket connection tests.
    """

    async def test_connect_establishes_websocket(
        self,
        xiaoyi_channel,
        mock_session,
        mock_ws,
        mock_auth_headers,
    ):
        """_connect should establish WebSocket connection with auth headers."""
        with patch(
            "copaw.app.channels.xiaoyi.channel.generate_auth_headers",
            return_value=mock_auth_headers,
        ):
            with patch("aiohttp.ClientSession", return_value=mock_session):
                await xiaoyi_channel._connect()

        mock_session.ws_connect.assert_called_once()
        assert xiaoyi_channel._connected is True
        assert xiaoyi_channel._ws == mock_ws

    async def test_connect_sends_init_message(
        self,
        xiaoyi_channel,
        mock_session,
        mock_ws,
        mock_auth_headers,
    ):
        """_connect should send init message after connection."""
        with patch(
            "copaw.app.channels.xiaoyi.channel.generate_auth_headers",
            return_value=mock_auth_headers,
        ):
            with patch("aiohttp.ClientSession", return_value=mock_session):
                await xiaoyi_channel._connect()

        mock_ws.send_json.assert_called_once()
        call_args = mock_ws.send_json.call_args
        sent_msg = call_args[0][0]
        assert sent_msg["msgType"] == "clawd_bot_init"
        assert sent_msg["agentId"] == xiaoyi_channel.agent_id

    async def test_connect_starts_heartbeat_and_receive(
        self,
        xiaoyi_channel,
        mock_session,
        mock_ws,
        mock_auth_headers,
    ):
        """_connect should start heartbeat and receive loops."""
        with patch(
            "copaw.app.channels.xiaoyi.channel.generate_auth_headers",
            return_value=mock_auth_headers,
        ):
            with patch("aiohttp.ClientSession", return_value=mock_session):
                await xiaoyi_channel._connect()

        assert xiaoyi_channel._heartbeat_task is not None
        assert xiaoyi_channel._receive_task is not None

    async def test_connect_handles_connection_error(
        self,
        xiaoyi_channel,
        mock_session,
        mock_auth_headers,
    ):
        """_connect should handle connection errors."""
        mock_session.ws_connect = AsyncMock(
            side_effect=aiohttp.ClientError("Connection failed"),
        )

        with patch(
            "copaw.app.channels.xiaoyi.channel.generate_auth_headers",
            return_value=mock_auth_headers,
        ):
            with patch("aiohttp.ClientSession", return_value=mock_session):
                with pytest.raises(aiohttp.ClientError):
                    await xiaoyi_channel._connect()

        assert xiaoyi_channel._connected is False


# =============================================================================
# P0/P1: Message Handling Tests
# =============================================================================


@pytest.mark.asyncio
class TestXiaoYiChannelMessageHandling:
    """
    P0/P1: Message handling tests.
    """

    async def test_handle_message_parses_json(self, xiaoyi_channel):
        """_handle_message should parse JSON messages."""
        message = {
            "msgType": "message",
            "agentId": "test_agent_123",
            "method": "message/stream",
            "params": {
                "sessionId": "session_123",
                "id": "task_123",
                "message": {
                    "parts": [{"kind": "text", "text": "Hello"}],
                },
            },
        }

        with patch.object(
            xiaoyi_channel,
            "_handle_a2a_request",
            new_callable=AsyncMock,
        ) as mock_handle:
            await xiaoyi_channel._handle_message(json.dumps(message))
            mock_handle.assert_called_once()

    async def test_handle_message_validates_agent_id(self, xiaoyi_channel):
        """_handle_message should validate agent_id."""
        message = {
            "msgType": "message",
            "agentId": "wrong_agent",
            "method": "message/stream",
        }

        with patch.object(
            xiaoyi_channel,
            "_handle_a2a_request",
            new_callable=AsyncMock,
        ) as mock_handle:
            await xiaoyi_channel._handle_message(json.dumps(message))
            mock_handle.assert_not_called()

    async def test_handle_message_handles_clear_context(self, xiaoyi_channel):
        """_handle_message should handle clearContext messages."""
        message = {
            "agentId": "test_agent_123",
            "method": "clearContext",
            "sessionId": "session_123",
            "id": "request_123",
        }

        with patch.object(
            xiaoyi_channel,
            "_handle_clear_context",
            new_callable=AsyncMock,
        ) as mock_handle:
            await xiaoyi_channel._handle_message(json.dumps(message))
            mock_handle.assert_called_once()

    async def test_handle_message_handles_tasks_cancel(self, xiaoyi_channel):
        """_handle_message should handle tasks/cancel messages."""
        message = {
            "agentId": "test_agent_123",
            "method": "tasks/cancel",
            "sessionId": "session_123",
            "id": "request_123",
            "taskId": "task_123",
        }

        with patch.object(
            xiaoyi_channel,
            "_handle_tasks_cancel",
            new_callable=AsyncMock,
        ) as mock_handle:
            await xiaoyi_channel._handle_message(json.dumps(message))
            mock_handle.assert_called_once()

    async def test_handle_message_handles_invalid_json(self, xiaoyi_channel):
        """_handle_message should handle invalid JSON gracefully."""
        # Should not raise
        await xiaoyi_channel._handle_message("invalid json{{{")


# =============================================================================
# P1: A2A Request Handling Tests
# =============================================================================


@pytest.mark.asyncio
class TestXiaoYiChannelA2ARequestHandling:
    """
    P1: A2A request handling tests.
    """

    async def test_handle_a2a_request_extracts_session_and_task_id(
        self,
        xiaoyi_channel,
    ):
        """_handle_a2a_request should extract session_id and task_id."""
        message = {
            "params": {
                "sessionId": "session_123",
                "id": "task_123",
                "message": {
                    "parts": [{"kind": "text", "text": "Hello"}],
                },
            },
        }

        mock_enqueue = MagicMock()
        xiaoyi_channel._enqueue = mock_enqueue

        await xiaoyi_channel._handle_a2a_request(message)

        assert xiaoyi_channel._session_task_map["session_123"] == "task_123"
        mock_enqueue.assert_called_once()

    async def test_handle_a2a_request_processes_text_parts(
        self,
        xiaoyi_channel,
    ):
        """_handle_a2a_request should process text parts."""
        message = {
            "params": {
                "sessionId": "session_123",
                "id": "task_123",
                "message": {
                    "parts": [
                        {"kind": "text", "text": "Hello"},
                        {"kind": "text", "text": "World"},
                    ],
                },
            },
        }

        mock_enqueue = MagicMock()
        xiaoyi_channel._enqueue = mock_enqueue

        await xiaoyi_channel._handle_a2a_request(message)

        call_args = mock_enqueue.call_args[0][0]
        content_parts = call_args["content_parts"]
        assert len(content_parts) == 1
        assert content_parts[0].text == "Hello World"

    async def test_handle_a2a_request_skips_empty_content(
        self,
        xiaoyi_channel,
    ):
        """_handle_a2a_request should skip empty content."""
        message = {
            "params": {
                "sessionId": "session_123",
                "id": "task_123",
                "message": {
                    "parts": [],
                },
            },
        }

        mock_enqueue = MagicMock()
        xiaoyi_channel._enqueue = mock_enqueue

        await xiaoyi_channel._handle_a2a_request(message)

        mock_enqueue.assert_not_called()

    async def test_handle_a2a_request_handles_missing_session(
        self,
        xiaoyi_channel,
    ):
        """_handle_a2a_request should handle missing session_id."""
        message = {
            "params": {
                "id": "task_123",
                "message": {
                    "parts": [{"kind": "text", "text": "Hello"}],
                },
            },
        }

        mock_enqueue = MagicMock()
        xiaoyi_channel._enqueue = mock_enqueue

        await xiaoyi_channel._handle_a2a_request(message)

        mock_enqueue.assert_not_called()


# =============================================================================
# P0: Send Message Tests
# =============================================================================


@pytest.mark.asyncio
class TestXiaoYiChannelSend:
    """
    P0: Send message tests.
    """

    async def test_send_skips_when_disabled(self, xiaoyi_channel):
        """send() should skip when channel is disabled."""
        xiaoyi_channel.enabled = False
        xiaoyi_channel._ws = MagicMock()
        xiaoyi_channel._connected = True

        await xiaoyi_channel.send("user123", "Hello")

        xiaoyi_channel._ws.send_json.assert_not_called()

    async def test_send_skips_when_not_connected(self, xiaoyi_channel):
        """send() should skip when not connected."""
        xiaoyi_channel.enabled = True
        xiaoyi_channel._connected = False

        await xiaoyi_channel.send("user123", "Hello")

    async def test_send_skips_empty_text(self, xiaoyi_channel, mock_ws):
        """send() should skip empty text."""
        xiaoyi_channel._ws = mock_ws
        xiaoyi_channel._connected = True
        xiaoyi_channel._session_task_map["session_123"] = "task_123"

        await xiaoyi_channel.send(
            "session_123",
            "   ",
            meta={"session_id": "session_123"},
        )

        mock_ws.send_json.assert_not_called()

    async def test_send_chunks_large_messages(self, xiaoyi_channel, mock_ws):
        """send() should chunk large messages."""
        xiaoyi_channel._ws = mock_ws
        xiaoyi_channel._connected = True
        xiaoyi_channel._session_task_map["session_123"] = "task_123"

        # Create a message larger than TEXT_CHUNK_LIMIT
        large_text = "A" * 5000

        with patch.object(
            xiaoyi_channel,
            "_chunk_text",
            return_value=["chunk1", "chunk2"],
        ) as mock_chunk:
            with patch.object(
                xiaoyi_channel,
                "_send_chunk",
                new_callable=AsyncMock,
            ) as mock_send:
                await xiaoyi_channel.send(
                    "session_123",
                    large_text,
                    meta={"session_id": "session_123"},
                )

                mock_chunk.assert_called_once_with(large_text)
                assert mock_send.call_count == 2

    async def test_send_final_message_sends_correct_format(
        self,
        xiaoyi_channel,
        mock_ws,
    ):
        """send_final_message should send correct format."""
        xiaoyi_channel._ws = mock_ws
        xiaoyi_channel._connected = True

        await xiaoyi_channel.send_final_message(
            "session_123",
            "task_123",
            "msg_123",
        )

        mock_ws.send_json.assert_called_once()
        call_args = mock_ws.send_json.call_args[0][0]
        assert call_args["msgType"] == "agent_response"
        assert call_args["agentId"] == xiaoyi_channel.agent_id


# =============================================================================
# P1: Text Chunking Tests
# =============================================================================


class TestXiaoYiChannelChunking:
    """
    P1: Text chunking tests.
    """

    def test_chunk_text_small_text_returns_single_chunk(self, xiaoyi_channel):
        """_chunk_text should return single chunk for small text."""
        text = "Small text"

        result = xiaoyi_channel._chunk_text(text)

        assert result == [text]

    def test_chunk_text_splits_at_newlines(self, xiaoyi_channel):
        """_chunk_text should try to split at newlines."""
        # Create text that would exceed limit but can split at newlines
        lines = ["Line" * 50] * 10
        text = "\n".join(lines)

        result = xiaoyi_channel._chunk_text(text)

        assert len(result) > 1
        # Each chunk should be within limit
        for chunk in result:
            assert len(chunk) <= 4000

    def test_chunk_text_handles_long_lines(self, xiaoyi_channel):
        """_chunk_text should handle lines longer than limit."""
        long_line = "A" * 5000

        result = xiaoyi_channel._chunk_text(long_line)

        assert len(result) > 1
        for chunk in result:
            assert len(chunk) <= 4000


# =============================================================================
# P1: Media Sending Tests
# =============================================================================


@pytest.mark.asyncio
class TestXiaoYiChannelMedia:
    """
    P1: Media sending tests.
    """

    async def test_send_media_skips_when_not_connected(self, xiaoyi_channel):
        """send_media should skip when not connected."""
        xiaoyi_channel._connected = False
        mock_part = MagicMock()

        await xiaoyi_channel.send_media("user123", mock_part)

    async def test_send_media_handles_image(self, xiaoyi_channel, mock_ws):
        """send_media should handle image parts."""
        xiaoyi_channel._ws = mock_ws
        xiaoyi_channel._connected = True
        xiaoyi_channel._session_task_map["session_123"] = "task_123"

        from agentscope_runtime.engine.schemas.agent_schemas import (
            ImageContent,
            ContentType,
        )

        image_part = ImageContent(
            type=ContentType.IMAGE,
            image_url="http://example.com/image.png",
        )

        await xiaoyi_channel.send_media(
            "session_123",
            image_part,
            meta={"session_id": "session_123"},
        )

        mock_ws.send_json.assert_called_once()
        call_args = mock_ws.send_json.call_args[0][0]
        msg_detail = json.loads(call_args["msgDetail"])
        assert msg_detail["result"]["artifact"]["parts"][0]["kind"] == "file"

    async def test_send_media_handles_unknown_type(
        self,
        xiaoyi_channel,
        mock_ws,
    ):
        """send_media should skip unknown part types."""
        xiaoyi_channel._ws = mock_ws
        xiaoyi_channel._connected = True
        xiaoyi_channel._session_task_map["session_123"] = "task_123"

        mock_part = MagicMock()
        mock_part.type = "unknown_type"

        await xiaoyi_channel.send_media(
            "session_123",
            mock_part,
            meta={"session_id": "session_123"},
        )

        mock_ws.send_json.assert_not_called()


# =============================================================================
# P1: Response Handling Tests
# =============================================================================


@pytest.mark.asyncio
class TestXiaoYiChannelResponseHandling:
    """
    P1: Response handling tests.
    """

    async def test_send_clear_context_response(self, xiaoyi_channel, mock_ws):
        """_send_clear_context_response should send correct format."""
        xiaoyi_channel._ws = mock_ws
        xiaoyi_channel._connected = True

        await xiaoyi_channel._send_clear_context_response(
            "req_123",
            "session_123",
        )

        mock_ws.send_json.assert_called_once()
        call_args = mock_ws.send_json.call_args[0][0]
        assert call_args["msgType"] == "agent_response"
        msg_detail = json.loads(call_args["msgDetail"])
        assert msg_detail["result"]["status"]["state"] == "cleared"

    async def test_send_tasks_cancel_response(self, xiaoyi_channel, mock_ws):
        """_send_tasks_cancel_response should send correct format."""
        xiaoyi_channel._ws = mock_ws
        xiaoyi_channel._connected = True

        await xiaoyi_channel._send_tasks_cancel_response(
            "req_123",
            "session_123",
        )

        mock_ws.send_json.assert_called_once()
        call_args = mock_ws.send_json.call_args[0][0]
        msg_detail = json.loads(call_args["msgDetail"])
        assert msg_detail["result"]["status"]["state"] == "canceled"


# =============================================================================
# P1: Session and Handle Resolution Tests
# =============================================================================


class TestXiaoYiChannelSessionResolution:
    """
    P1: Session and handle resolution tests.
    """

    def test_resolve_session_id_with_meta(self, xiaoyi_channel):
        """resolve_session_id should use channel_meta if provided."""
        result = xiaoyi_channel.resolve_session_id(
            "sender_123",
            {"session_id": "meta_session"},
        )

        assert result == "xiaoyi:meta_session"

    def test_resolve_session_id_without_meta(self, xiaoyi_channel):
        """resolve_session_id should use sender_id if no meta."""
        result = xiaoyi_channel.resolve_session_id("sender_123", None)

        assert result == "xiaoyi:sender_123"

    def test_get_to_handle_from_request_with_meta(self, xiaoyi_channel):
        """get_to_handle_from_request should use channel_meta session_id."""
        mock_request = MagicMock()
        mock_request.channel_meta = {"session_id": "meta_session_123"}
        mock_request.user_id = "user_123"

        result = xiaoyi_channel.get_to_handle_from_request(mock_request)

        assert result == "meta_session_123"

    def test_get_to_handle_from_request_fallback_to_user_id(
        self,
        xiaoyi_channel,
    ):
        """get_to_handle_from_request should fallback to user_id."""
        mock_request = MagicMock()
        mock_request.channel_meta = {}
        mock_request.user_id = "user_123"

        result = xiaoyi_channel.get_to_handle_from_request(mock_request)

        assert result == "user_123"

    def test_to_handle_from_target_with_xiaoyi_prefix(self, xiaoyi_channel):
        """to_handle_from_target should strip xiaoyi: prefix."""
        result = xiaoyi_channel.to_handle_from_target(
            user_id="user_123",
            session_id="xiaoyi:session_123",
        )

        assert result == "session_123"

    def test_to_handle_from_target_fallback_to_user_id(self, xiaoyi_channel):
        """to_handle_from_target should fallback to user_id."""
        result = xiaoyi_channel.to_handle_from_target(
            user_id="user_123",
            session_id="other:session",
        )

        assert result == "user_123"


# =============================================================================
# P1: Artifact Building Tests
# =============================================================================


class TestXiaoYiChannelArtifactBuilding:
    """
    P1: Artifact message building tests.
    """

    def test_build_artifact_msg_basic(self, xiaoyi_channel):
        """_build_artifact_msg should build correct message structure."""
        parts = [{"kind": "text", "text": "Hello"}]

        result = xiaoyi_channel._build_artifact_msg(
            "session_123",
            "task_123",
            "msg_123",
            parts,
        )

        assert result["msgType"] == "agent_response"
        assert result["agentId"] == xiaoyi_channel.agent_id
        assert result["sessionId"] == "session_123"
        assert result["taskId"] == "task_123"

        msg_detail = json.loads(result["msgDetail"])
        assert msg_detail["jsonrpc"] == "2.0"
        assert msg_detail["id"] == "msg_123"
        assert msg_detail["result"]["kind"] == "artifact-update"
        assert msg_detail["result"]["append"] is True

    def test_build_artifact_msg_with_final(self, xiaoyi_channel):
        """_build_artifact_msg should set final flag when specified."""
        parts = [{"kind": "text", "text": ""}]

        result = xiaoyi_channel._build_artifact_msg(
            "session_123",
            "task_123",
            "msg_123",
            parts,
            last_chunk=True,
            final=True,
        )

        msg_detail = json.loads(result["msgDetail"])
        assert msg_detail["result"]["lastChunk"] is True
        assert msg_detail["result"]["final"] is True


# =============================================================================
# P1: Parts Extraction Tests
# =============================================================================


class TestXiaoYiChannelPartsExtraction:
    """
    P1: XiaoYi parts extraction tests.
    """

    def test_extract_xiaoyi_parts_with_text(self, xiaoyi_channel):
        """_extract_xiaoyi_parts should extract text parts."""
        mock_message = MagicMock()
        mock_message.type = "message"

        from agentscope_runtime.engine.schemas.agent_schemas import (
            TextContent,
            ContentType,
        )

        text_content = TextContent(type=ContentType.TEXT, text="Hello World")
        mock_message.content = [text_content]

        result = xiaoyi_channel._extract_xiaoyi_parts(mock_message)

        assert len(result) == 1
        assert result[0]["kind"] == "text"
        assert "\n\nHello World" in result[0]["text"]

    def test_extract_xiaoyi_parts_empty_content(self, xiaoyi_channel):
        """_extract_xiaoyi_parts should handle empty content."""
        mock_message = MagicMock()
        mock_message.type = "message"
        mock_message.content = []

        result = xiaoyi_channel._extract_xiaoyi_parts(mock_message)

        assert result == []


# =============================================================================
# P1: Session Task Map Tests
# =============================================================================


class TestXiaoYiChannelSessionTaskMap:
    """
    P1: Session to task mapping tests.
    """

    def test_session_task_map_stores_mapping(self, xiaoyi_channel):
        """_session_task_map should store session to task mapping."""
        xiaoyi_channel._session_task_map["session_123"] = "task_123"

        assert xiaoyi_channel._session_task_map["session_123"] == "task_123"

    def test_session_task_map_pop_removes(self, xiaoyi_channel):
        """_session_task_map pop should remove mapping."""
        xiaoyi_channel._session_task_map["session_123"] = "task_123"

        result = xiaoyi_channel._session_task_map.pop("session_123", None)

        assert result == "task_123"
        assert "session_123" not in xiaoyi_channel._session_task_map


# =============================================================================
# P1: Connection Registry Tests
# =============================================================================


@pytest.mark.asyncio
class TestXiaoYiChannelConnectionRegistry:
    """
    P1: Connection registry tests.
    """

    async def test_unregister_connection_removes_from_registry(
        self,
        xiaoyi_channel,
    ):
        """_unregister_connection should remove from active connections."""
        from copaw.app.channels.xiaoyi import channel as xiaoyi_module

        # Add to registry first
        async with xiaoyi_module._active_connections_lock:
            xiaoyi_module._active_connections[
                xiaoyi_channel.agent_id
            ] = xiaoyi_channel

        # Unregister
        await xiaoyi_channel._unregister_connection()

        async with xiaoyi_module._active_connections_lock:
            assert (
                xiaoyi_channel.agent_id
                not in xiaoyi_module._active_connections
            )


# =============================================================================
# P1: Build Agent Request Tests
# =============================================================================


class TestXiaoYiChannelBuildAgentRequest:
    """
    P1: Build agent request from native payload tests.
    """

    def test_build_agent_request_from_native_basic(self, xiaoyi_channel):
        """build_agent_request_from_native should build request from native payload."""
        payload = {
            "channel_id": "xiaoyi",
            "sender_id": "user_123",
            "content_parts": [{"type": "text", "text": "Hello"}],
            "meta": {"session_id": "session_123", "task_id": "task_123"},
        }

        result = xiaoyi_channel.build_agent_request_from_native(payload)

        assert result.user_id == "user_123"
        assert result.channel == "xiaoyi"
        assert result.channel_meta == {
            "session_id": "session_123",
            "task_id": "task_123",
        }

    def test_build_agent_request_from_native_empty_payload(
        self,
        xiaoyi_channel,
    ):
        """build_agent_request_from_native should handle empty payload."""
        payload = {}

        result = xiaoyi_channel.build_agent_request_from_native(payload)

        assert result.channel == "xiaoyi"  # Default channel
        assert result.user_id == ""  # Empty sender
