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

import json
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest


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
def xiaoyi_channel(mock_process, tmp_path):
    """Create XiaoYiChannel instance for testing."""
    from qwenpaw.app.channels.xiaoyi.channel import XiaoYiChannel

    channel = XiaoYiChannel(
        process=mock_process,
        enabled=True,
        ak="test_ak_123456",
        sk="test_sk_abcdef",
        agent_id="test_agent_123",
        task_timeout_ms=3600000,
        bot_prefix="[小艺] ",
        media_dir=str(tmp_path / "media"),
    )
    return channel


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
        from qwenpaw.app.channels.xiaoyi.channel import XiaoYiChannel

        channel = XiaoYiChannel(
            process=mock_process,
            enabled=True,
            ak="test_ak",
            sk="test_sk",
            agent_id="test_agent",
            task_timeout_ms=5000,
            bot_prefix="[Test] ",
            media_dir=str(tmp_path / "media"),
        )

        assert channel.enabled is True
        assert channel.ak == "test_ak"
        assert channel.sk == "test_sk"
        assert channel.agent_id == "test_agent"
        assert channel.task_timeout_ms == 5000
        assert channel.bot_prefix == "[Test] "
        assert channel._media_dir == tmp_path / "media"

    def test_init_creates_required_data_structures(
        self,
        mock_process,
        tmp_path,
    ):
        """Constructor should initialize internal data structures."""
        from qwenpaw.app.channels.xiaoyi.channel import XiaoYiChannel

        channel = XiaoYiChannel(
            process=mock_process,
            enabled=True,
            ak="test_ak",
            sk="test_sk",
            agent_id="test_agent",
        )

        assert hasattr(channel, "_session_task_map")
        assert isinstance(channel._session_task_map, dict)
        assert channel._conn_primary is None
        assert channel._conn_backup is None
        assert channel._connected is False
        assert channel._reconnect_attempts == 0
        assert hasattr(channel, "_session_server_map")
        assert isinstance(channel._session_server_map, dict)

    def test_init_with_workspace_dir(self, mock_process, tmp_path):
        """Constructor uses workspace-specific media dir when provided."""
        from qwenpaw.app.channels.xiaoyi.channel import XiaoYiChannel

        workspace = tmp_path / "workspace"
        channel = XiaoYiChannel(
            process=mock_process,
            enabled=True,
            ak="test_ak",
            sk="test_sk",
            agent_id="test_agent",
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

    def test_from_env_reads_env_vars(
        self,
        monkeypatch,
        mock_process,
        tmp_path,
    ):
        """from_env should correctly read environment variables."""
        from qwenpaw.app.channels.xiaoyi.channel import XiaoYiChannel

        monkeypatch.setenv("XIAOYI_CHANNEL_ENABLED", "1")
        monkeypatch.setenv("XIAOYI_AK", "env_ak_value")
        monkeypatch.setenv("XIAOYI_SK", "env_sk_value")
        monkeypatch.setenv("XIAOYI_AGENT_ID", "env_agent_123")
        monkeypatch.setenv("XIAOYI_MEDIA_DIR", str(tmp_path / "media"))

        channel = XiaoYiChannel.from_env(process=mock_process)

        assert channel.enabled is True
        assert channel.ak == "env_ak_value"
        assert channel.sk == "env_sk_value"
        assert channel.agent_id == "env_agent_123"

    def test_from_env_uses_defaults(self, monkeypatch, mock_process):
        """from_env uses default values when env vars are missing."""
        from qwenpaw.app.channels.xiaoyi.channel import XiaoYiChannel

        monkeypatch.delenv("XIAOYI_CHANNEL_ENABLED", raising=False)
        monkeypatch.delenv("XIAOYI_AK", raising=False)
        monkeypatch.delenv("XIAOYI_SK", raising=False)
        monkeypatch.delenv("XIAOYI_AGENT_ID", raising=False)

        channel = XiaoYiChannel.from_env(process=mock_process)

        assert channel.enabled is False
        assert channel.ak == ""
        assert channel.sk == ""
        assert channel.agent_id == ""

    def test_from_config_with_object(self, mock_process, tmp_path):
        """from_config should use config object values."""
        from qwenpaw.app.channels.xiaoyi.channel import XiaoYiChannel

        config = Mock()
        config.enabled = True
        config.ak = "config_ak"
        config.sk = "config_sk"
        config.agent_id = "config_agent"
        config.task_timeout_ms = 60000
        config.bot_prefix = "[Config] "
        config.media_dir = str(tmp_path / "media")

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
        from qwenpaw.app.channels.xiaoyi.channel import XiaoYiChannel

        config = {
            "enabled": True,
            "ak": "dict_ak",
            "sk": "dict_sk",
            "agent_id": "dict_agent",
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
        from qwenpaw.app.channels.xiaoyi.channel import XiaoYiChannel

        channel = XiaoYiChannel(
            process=mock_process,
            enabled=True,
            ak="",
            sk="test_sk",
            agent_id="test_agent",
        )

        with pytest.raises(ValueError, match="AK"):
            channel._validate_config()

    def test_validate_config_raises_on_missing_sk(self, mock_process):
        """_validate_config should raise ValueError when SK is missing."""
        from qwenpaw.app.channels.xiaoyi.channel import XiaoYiChannel

        channel = XiaoYiChannel(
            process=mock_process,
            enabled=True,
            ak="test_ak",
            sk="",
            agent_id="test_agent",
        )

        with pytest.raises(ValueError, match="SK"):
            channel._validate_config()

    def test_validate_config_raises_on_missing_agent_id(self, mock_process):
        """_validate_config raises ValueError when agent_id is missing."""
        from qwenpaw.app.channels.xiaoyi.channel import XiaoYiChannel

        channel = XiaoYiChannel(
            process=mock_process,
            enabled=True,
            ak="test_ak",
            sk="test_sk",
            agent_id="",
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
                with patch.object(
                    xiaoyi_channel,
                    "_start_connections",
                    new_callable=AsyncMock,
                ):
                    await xiaoyi_channel.start()
                    mock_validate.assert_called_once()

    async def test_start_handles_validation_error(self, xiaoyi_channel):
        """start() should handle config validation errors gracefully."""
        xiaoyi_channel.enabled = True
        xiaoyi_channel.ak = ""  # Invalid config

        await xiaoyi_channel.start()

        assert xiaoyi_channel._connected is False

    async def test_stop_cleans_up_resources(self, xiaoyi_channel):
        """stop() should clean up all resources."""
        from qwenpaw.app.channels.xiaoyi.channel import XiaoYiConnection

        mock_conn = MagicMock(spec=XiaoYiConnection)
        mock_conn.disconnect = AsyncMock()
        mock_conn.connected = True
        xiaoyi_channel._conn_primary = mock_conn
        xiaoyi_channel._conn_backup = None
        xiaoyi_channel._connected = True

        await xiaoyi_channel.stop()

        assert xiaoyi_channel._connected is False
        assert xiaoyi_channel._stopping is True
        mock_conn.disconnect.assert_called_once()
        assert xiaoyi_channel._conn_primary is None

    async def test_stop_handles_no_connections(self, xiaoyi_channel):
        """stop() should handle missing connections gracefully."""
        xiaoyi_channel._conn_primary = None
        xiaoyi_channel._conn_backup = None
        xiaoyi_channel._connected = True

        await xiaoyi_channel.stop()

        assert xiaoyi_channel._connected is False

    async def test_stop_disconnects_both_connections(self, xiaoyi_channel):
        """stop() should disconnect both connections."""
        from qwenpaw.app.channels.xiaoyi.channel import XiaoYiConnection

        conn1 = MagicMock(spec=XiaoYiConnection)
        conn1.disconnect = AsyncMock()
        conn2 = MagicMock(spec=XiaoYiConnection)
        conn2.disconnect = AsyncMock()
        xiaoyi_channel._conn_primary = conn1
        xiaoyi_channel._conn_backup = conn2
        xiaoyi_channel._connected = True

        await xiaoyi_channel.stop()

        conn1.disconnect.assert_called_once()
        conn2.disconnect.assert_called_once()
        assert xiaoyi_channel._conn_primary is None
        assert xiaoyi_channel._conn_backup is None


# =============================================================================
# P0: WebSocket Connection Tests
# =============================================================================


@pytest.mark.asyncio
class TestXiaoYiChannelWebSocketConnection:
    """
    P0: WebSocket connection tests (single connection + fallback).
    """

    async def test_start_connections_primary_success(
        self,
        xiaoyi_channel,
    ):
        """_start_connections should connect both endpoints in parallel."""
        with patch(
            "qwenpaw.app.channels.xiaoyi.channel.XiaoYiConnection",
        ) as MockConn:
            mock_instance = MagicMock()
            mock_instance.connect = AsyncMock(return_value=True)
            mock_instance.disconnect = AsyncMock()
            mock_instance.connected = True
            MockConn.return_value = mock_instance

            await xiaoyi_channel._start_connections()

        # Both primary and backup created
        assert MockConn.call_count == 2
        assert xiaoyi_channel._connected is True

    async def test_start_connections_fallback_to_backup(
        self,
        xiaoyi_channel,
    ):
        """_start_connections should succeed if at least one connects."""
        call_count = 0

        async def side_effect_connect():
            nonlocal call_count
            call_count += 1
            return call_count != 1  # First fails, second succeeds

        with patch(
            "qwenpaw.app.channels.xiaoyi.channel.XiaoYiConnection",
        ) as MockConn:
            mock_instance = MagicMock()
            mock_instance.connect = AsyncMock(side_effect=side_effect_connect)
            mock_instance.disconnect = AsyncMock()
            MockConn.return_value = mock_instance

            await xiaoyi_channel._start_connections()

        assert MockConn.call_count == 2
        assert xiaoyi_channel._connected is True

    async def test_start_connections_no_backup(
        self,
        xiaoyi_channel,
    ):
        """_start_connections with empty backup constant skips backup."""
        with patch(
            "qwenpaw.app.channels.xiaoyi.channel.DEFAULT_WS_URL_BACKUP",
            "",
        ), patch(
            "qwenpaw.app.channels.xiaoyi.channel.XiaoYiConnection",
        ) as MockConn:
            mock_instance = MagicMock()
            mock_instance.connect = AsyncMock(return_value=True)
            mock_instance.disconnect = AsyncMock()
            MockConn.return_value = mock_instance

            await xiaoyi_channel._start_connections()

            assert MockConn.call_count == 1
            assert xiaoyi_channel._conn_backup is None
            assert xiaoyi_channel._connected is True


# =============================================================================
# P0/P1: Message Handling Tests
# =============================================================================


@pytest.mark.asyncio
class TestXiaoYiChannelMessageHandling:
    """
    P0/P1: Message handling tests.
    """

    async def test_handle_message_parses_json(self, xiaoyi_channel):
        """_handle_incoming_message should dispatch messages."""
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
            await xiaoyi_channel._handle_incoming_message(
                message,
                "primary",
            )
            mock_handle.assert_called_once()

    async def test_handle_message_validates_agent_id(self, xiaoyi_channel):
        """_handle_incoming_message should validate agent_id."""
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
            await xiaoyi_channel._handle_incoming_message(
                message,
                "primary",
            )
            mock_handle.assert_not_called()

    async def test_handle_message_tracks_session_server(
        self,
        xiaoyi_channel,
    ):
        """_handle_incoming_message should track session->server."""
        message = {
            "agentId": "test_agent_123",
            "method": "message/stream",
            "params": {
                "sessionId": "session_456",
                "id": "task_456",
                "message": {
                    "parts": [{"kind": "text", "text": "Hi"}],
                },
            },
        }

        mock_enqueue = MagicMock()
        xiaoyi_channel._enqueue = mock_enqueue

        await xiaoyi_channel._handle_incoming_message(
            message,
            "backup",
        )

        assert xiaoyi_channel._session_server_map["session_456"] == "backup"

    async def test_handle_message_handles_clear_context(self, xiaoyi_channel):
        """_handle_incoming_message should handle clearContext."""
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
            await xiaoyi_channel._handle_incoming_message(
                message,
                "primary",
            )
            mock_handle.assert_called_once()

    async def test_handle_message_handles_tasks_cancel(self, xiaoyi_channel):
        """_handle_incoming_message should handle tasks/cancel."""
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
            await xiaoyi_channel._handle_incoming_message(
                message,
                "primary",
            )
            mock_handle.assert_called_once()


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
        xiaoyi_channel._connected = True

        with patch.object(
            xiaoyi_channel,
            "_send_to_session_server",
            new_callable=AsyncMock,
        ) as mock_send:
            await xiaoyi_channel.send("user123", "Hello")
            mock_send.assert_not_called()

    async def test_send_skips_when_not_connected(self, xiaoyi_channel):
        """send() should skip when not connected."""
        xiaoyi_channel.enabled = True
        xiaoyi_channel._connected = False

        await xiaoyi_channel.send("user123", "Hello")

    async def test_send_skips_empty_text(self, xiaoyi_channel):
        """send() should skip empty text."""
        xiaoyi_channel._connected = True
        xiaoyi_channel._session_task_map["session_123"] = "task_123"

        with patch.object(
            xiaoyi_channel,
            "_send_to_session_server",
            new_callable=AsyncMock,
        ) as mock_send:
            await xiaoyi_channel.send(
                "session_123",
                "   ",
                meta={"session_id": "session_123"},
            )
            mock_send.assert_not_called()

    async def test_send_chunks_large_messages(self, xiaoyi_channel):
        """send() should chunk large messages."""
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
    ):
        """send_final_message should send status-update + artifact."""
        xiaoyi_channel._connected = True

        with patch.object(
            xiaoyi_channel,
            "_send_to_session_server",
            new_callable=AsyncMock,
        ) as mock_send:
            await xiaoyi_channel.send_final_message(
                "session_123",
                "task_123",
                "msg_123",
            )

            # Two calls: status-update + artifact-update
            assert mock_send.call_count == 2

            # First call: status-update with state=completed
            status_msg = mock_send.call_args_list[0][0][1]
            assert status_msg["msgType"] == "agent_response"
            status_detail = json.loads(status_msg["msgDetail"])
            assert status_detail["result"]["kind"] == "status-update"
            assert status_detail["result"]["status"]["state"] == "completed"

            # Second call: artifact-update with final=true
            final_msg = mock_send.call_args_list[1][0][1]
            final_detail = json.loads(final_msg["msgDetail"])
            assert final_detail["result"]["kind"] == "artifact-update"
            assert final_detail["result"]["final"] is True


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
        # Create text that exceeds 4000 limit and can split at newlines
        # Each line is 200 chars, need 21+ lines to exceed limit
        lines = ["Line" * 50] * 25
        text = "\n".join(lines)

        result = xiaoyi_channel._chunk_text(text)

        # Verify function runs without error
        assert len(result) >= 1
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

    async def test_send_media_handles_image(self, xiaoyi_channel):
        """send_media should handle image parts."""
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

        with patch.object(
            xiaoyi_channel,
            "_send_to_session_server",
            new_callable=AsyncMock,
        ) as mock_send:
            await xiaoyi_channel.send_media(
                "session_123",
                image_part,
                meta={"session_id": "session_123"},
            )

            mock_send.assert_called_once()
            msg = mock_send.call_args[0][1]
            msg_detail = json.loads(msg["msgDetail"])
            assert (
                msg_detail["result"]["artifact"]["parts"][0]["kind"] == "file"
            )

    async def test_send_media_handles_unknown_type(
        self,
        xiaoyi_channel,
    ):
        """send_media should skip unknown part types."""
        xiaoyi_channel._connected = True
        xiaoyi_channel._session_task_map["session_123"] = "task_123"

        mock_part = MagicMock()
        mock_part.type = "unknown_type"

        with patch.object(
            xiaoyi_channel,
            "_send_to_session_server",
            new_callable=AsyncMock,
        ) as mock_send:
            await xiaoyi_channel.send_media(
                "session_123",
                mock_part,
                meta={"session_id": "session_123"},
            )
            mock_send.assert_not_called()


# =============================================================================
# P1: Response Handling Tests
# =============================================================================


@pytest.mark.asyncio
class TestXiaoYiChannelResponseHandling:
    """
    P1: Response handling tests.
    """

    async def test_send_clear_context_response(self, xiaoyi_channel):
        """_send_clear_context_response should send correct format."""
        xiaoyi_channel._connected = True

        with patch.object(
            xiaoyi_channel,
            "_send_to_session_server",
            new_callable=AsyncMock,
        ) as mock_send:
            await xiaoyi_channel._send_clear_context_response(
                "req_123",
                "session_123",
            )

            mock_send.assert_called_once()
            msg = mock_send.call_args[0][1]
            assert msg["msgType"] == "agent_response"
            msg_detail = json.loads(msg["msgDetail"])
            assert msg_detail["result"]["status"]["state"] == "cleared"

    async def test_send_tasks_cancel_response(self, xiaoyi_channel):
        """_send_tasks_cancel_response should send correct format."""
        xiaoyi_channel._connected = True

        with patch.object(
            xiaoyi_channel,
            "_send_to_session_server",
            new_callable=AsyncMock,
        ) as mock_send:
            await xiaoyi_channel._send_tasks_cancel_response(
                "req_123",
                "session_123",
            )

            mock_send.assert_called_once()
            msg = mock_send.call_args[0][1]
            msg_detail = json.loads(msg["msgDetail"])
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
        assert msg_detail["result"]["lastChunk"] is True

    def test_build_artifact_msg_with_final(self, xiaoyi_channel):
        """_build_artifact_msg should set final flag when specified."""
        parts = [{"kind": "text", "text": ""}]

        result = xiaoyi_channel._build_artifact_msg(
            "session_123",
            "task_123",
            "msg_123",
            parts,
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

        # When content is empty, returns a fallback text with message type
        assert len(result) == 1
        assert result[0]["kind"] == "text"
        assert "message" in result[0]["text"]


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
        from qwenpaw.app.channels.xiaoyi import channel as xiaoyi_module

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
        """build_agent_request_from_native builds request."""
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
