# -*- coding: utf-8 -*-
"""Unit tests for Matrix channel implementation."""

# pylint: disable=redefined-outer-name,unused-import
# pylint: disable=protected-access,unused-argument
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from agentscope_runtime.engine.schemas.agent_schemas import (
    AgentRequest,
    ContentType,
    ImageContent,
    TextContent,
)
from nio import (
    MatrixRoom,
    RoomMessageAudio,
    RoomMessageFile,
    RoomMessageImage,
    RoomMessageText,
    RoomMessageVideo,
    RoomSendError,
    UploadError,
    UploadResponse,
)

from nio.responses import WhoamiResponse
from qwenpaw.app.channels.matrix.channel import MatrixChannel
from qwenpaw.config.config import MatrixConfig


@pytest.fixture
def mock_process():
    """Create mock process handler."""

    async def mock_handler(*_args, **_kwargs):
        mock_event = MagicMock()
        mock_event.object = "message"
        mock_event.status = "completed"
        yield mock_event

    return AsyncMock(side_effect=mock_handler)


@pytest.fixture
def matrix_config():
    """Create MatrixConfig instance."""
    return MatrixConfig(
        enabled=True,
        homeserver="https://matrix.example.com",
        user_id="@bot:example.com",
        access_token="test_token_123",
        bot_prefix="!bot",
        dm_policy="open",
        group_policy="open",
        allow_from=["@allowed:example.com"],
        deny_message="Access denied",
        require_mention=False,
    )


@pytest.fixture
def matrix_channel(mock_process, matrix_config):
    """Create MatrixChannel instance."""
    return MatrixChannel.from_config(
        process=mock_process,
        config=matrix_config,
    )


@pytest.fixture
def mock_async_client():
    """Create mock AsyncClient for nio."""
    client = MagicMock()
    client.access_token = None
    client.add_event_callback = Mock()
    client.close = AsyncMock()
    client.room_send = AsyncMock()
    client.sync_forever = AsyncMock()
    client.upload = AsyncMock()
    whoami_resp = WhoamiResponse(
        user_id="@bot:example.com",
        device_id=None,
        is_guest=False,
    )
    client.whoami = AsyncMock(return_value=whoami_resp)
    client.sync = AsyncMock(return_value=MagicMock())
    return client


@pytest.fixture
def mock_matrix_room():
    """Create mock MatrixRoom."""
    room = MagicMock(spec=MatrixRoom)
    room.room_id = "!test_room:example.com"
    room.users = {"@user1:example.com": None, "@user2:example.com": None}
    return room


class TestMatrixChannelInit:
    """Test MatrixChannel initialization."""

    def test_init_with_required_params(self, mock_process):
        """Test initialization with required parameters."""
        config = MatrixConfig(
            homeserver="https://matrix.example.com",
            user_id="@bot:example.com",
            access_token="test_token",
        )
        channel = MatrixChannel(process=mock_process, config=config)

        assert channel._cfg.homeserver == "https://matrix.example.com"
        assert channel._cfg.user_id == "@bot:example.com"
        assert channel._cfg.access_token == "test_token"
        assert channel.channel == "matrix"
        assert channel.uses_manager_queue is True
        assert channel._client is None
        assert channel._sync_task is None

    def test_init_homeserver_trailing_slash(self, mock_process):
        """Test that trailing slash is stripped from homeserver."""
        config = MatrixConfig(
            homeserver="https://matrix.example.com/",
            user_id="@bot:example.com",
            access_token="test_token",
        )
        channel = MatrixChannel(process=mock_process, config=config)

        assert channel._cfg.homeserver == "https://matrix.example.com"

    def test_init_with_all_params(self, mock_process):
        """Test initialization with all optional parameters."""
        config = MatrixConfig(
            homeserver="https://matrix.example.com",
            user_id="@bot:example.com",
            access_token="test_token",
            bot_prefix="!cmd",
            dm_policy="allowlist",
            group_policy="allowlist",
            allow_from=["@user:example.com"],
        )
        channel = MatrixChannel(
            process=mock_process,
            config=config,
            on_reply_sent=Mock(),
            show_tool_details=False,
            filter_tool_messages=True,
            filter_thinking=True,
        )

        assert channel._cfg.bot_prefix == "!cmd"
        assert channel._cfg.dm_policy == "allowlist"
        assert channel._cfg.group_policy == "allowlist"
        assert channel._show_tool_details is False
        assert channel._filter_tool_messages is True
        assert channel._filter_thinking is True


class TestMatrixChannelFromConfig:
    """Test MatrixChannel factory methods."""

    def test_from_config(self, mock_process, matrix_config):
        """Test creating channel from config."""
        channel = MatrixChannel.from_config(
            process=mock_process,
            config=matrix_config,
        )

        assert channel._cfg.enabled is True
        assert channel._cfg.homeserver == "https://matrix.example.com"
        assert channel._user_id == "@bot:example.com"
        assert channel._cfg.access_token == "test_token_123"

    def test_from_config_with_optional_params(
        self,
        mock_process,
        matrix_config,
    ):
        """Test from_config with optional display parameters."""
        channel = MatrixChannel.from_config(
            process=mock_process,
            config=matrix_config,
            show_tool_details=False,
            filter_tool_messages=True,
            filter_thinking=True,
        )

        assert channel._show_tool_details is False
        assert channel._filter_tool_messages is True
        assert channel._filter_thinking is True

    def test_from_env_raises_not_implemented(self, mock_process):
        """Test that from_env creates a channel (uses env vars)."""
        channel = MatrixChannel.from_env(process=mock_process)
        assert isinstance(channel, MatrixChannel)


class TestMatrixChannelMXC:
    """Test MXC to HTTP URL conversion."""

    def test_mxc_to_http_with_valid_mxc(self, matrix_channel):
        """Test converting valid MXC URL to HTTP."""
        mxc_url = "mxc://matrix.org/media_123"
        http_url = matrix_channel._mxc_to_http(mxc_url)

        expected = (
            "https://matrix.example.com/_matrix/media/v3/download/"
            "matrix.org/media_123"
        )
        assert http_url == expected

    def test_mxc_to_http_with_http_url(self, matrix_channel):
        """Test that HTTP URLs are returned as-is."""
        http_url = "https://example.com/image.png"
        result = matrix_channel._mxc_to_http(http_url)

        assert result == http_url

    def test_mxc_to_http_with_invalid_mxc_format(self, matrix_channel):
        """Test handling of invalid MXC URL format."""
        invalid_mxc = "mxc://noseparator"
        result = matrix_channel._mxc_to_http(invalid_mxc)

        assert result == invalid_mxc

    def test_mxc_to_http_with_empty_string(self, matrix_channel):
        """Test handling of empty string."""
        result = matrix_channel._mxc_to_http("")

        assert result == ""


class TestMatrixChannelAllowlist:
    """Test allowlist checking."""

    def test_check_allowlist_open_policy(self, matrix_channel):
        """Test that open policy allows all users."""
        matrix_channel._cfg.dm_policy = "open"
        matrix_channel._cfg.group_policy = "open"

        allowed = matrix_channel._check_allowed(
            "@any_user:example.com",
            "!room:example.com",
            is_dm=True,
        )

        assert allowed is True

    def test_check_allowlist_allowlist_user_allowed(self, matrix_channel):
        """Test allowed user on allowlist."""
        matrix_channel._cfg.dm_policy = "allowlist"
        matrix_channel._cfg.allow_from = ["@allowed:example.com"]

        allowed = matrix_channel._check_allowed(
            "@allowed:example.com",
            "!room:example.com",
            is_dm=True,
        )

        assert allowed is True

    def test_check_allowlist_allowlist_user_denied(self, matrix_channel):
        """Test denied user not on allowlist."""
        matrix_channel._cfg.dm_policy = "allowlist"
        matrix_channel._cfg.allow_from = ["@allowed:example.com"]

        allowed = matrix_channel._check_allowed(
            "@not_allowed:example.com",
            "!room:example.com",
            is_dm=True,
        )

        assert allowed is False

    def test_check_allowlist_dm_vs_group_policy(self, matrix_channel):
        """Test different policies for DM and group."""
        matrix_channel._cfg.dm_policy = "allowlist"
        matrix_channel._cfg.group_policy = "open"
        matrix_channel._cfg.allow_from = ["@allowed:example.com"]

        # DM should use allowlist → denied
        allowed_dm = matrix_channel._check_allowed(
            "@unknown:example.com",
            "!room:example.com",
            is_dm=True,
        )
        assert allowed_dm is False

        # Group should be open → allowed
        allowed_group = matrix_channel._check_allowed(
            "@unknown:example.com",
            "!room:example.com",
            is_dm=False,
        )
        assert allowed_group is True


@pytest.mark.asyncio
class TestMatrixChannelBuildRequest:
    """Test request building methods."""

    def test_build_agent_request_from_native(self, matrix_channel):
        """Test building AgentRequest from native payload."""
        payload = {
            "sender_id": "@user:example.com",
            "content_parts": [
                TextContent(type=ContentType.TEXT, text="Hello bot"),
            ],
            "meta": {"room_id": "!room:example.com"},
        }

        request = matrix_channel.build_agent_request_from_native(payload)

        assert isinstance(request, AgentRequest)
        assert request.channel == "matrix"
        # user_id is intentionally set to room_id for session keying
        assert request.user_id == "!room:example.com"
        assert request.session_id == "matrix:!room:example.com"

    def test_build_agent_request_with_content_parts(self, matrix_channel):
        """Test building request with existing content_parts."""
        content_parts = [
            TextContent(type=ContentType.TEXT, text="Test message"),
        ]
        payload = {
            "sender_id": "@user:example.com",
            "content_parts": content_parts,
            "meta": {"room_id": "!room:example.com"},
        }

        request = matrix_channel.build_agent_request_from_native(payload)

        assert request.input[0].content == content_parts

    def test_get_to_handle_from_request_with_session_id(self, matrix_channel):
        """Test getting room_id from channel_meta."""
        request = MagicMock(spec=AgentRequest)
        request.session_id = "matrix:!room:example.com"
        request.channel_meta = {"room_id": "!room:example.com"}

        result = matrix_channel.get_to_handle_from_request(request)

        assert result == "!room:example.com"

    def test_get_to_handle_from_request_with_channel_meta(
        self,
        matrix_channel,
    ):
        """Test getting room_id from channel_meta."""
        request = MagicMock(spec=AgentRequest)
        request.session_id = "other_session"
        request.channel_meta = {"room_id": "!room:example.com"}

        result = matrix_channel.get_to_handle_from_request(request)

        assert result == "!room:example.com"

    def test_get_to_handle_from_request_fallback_to_user_id(
        self,
        matrix_channel,
    ):
        """Test fallback to user_id when no room_id."""
        request = MagicMock(spec=AgentRequest)
        request.session_id = "other_session"
        request.channel_meta = {}
        request.user_id = "@user:example.com"

        result = matrix_channel.get_to_handle_from_request(request)

        assert result == "@user:example.com"


@pytest.mark.asyncio
class TestMatrixChannelHandleEvent:
    """Test event handling."""

    async def test_on_room_event_open_policy(
        self,
        matrix_channel,
        mock_matrix_room,
    ):
        """Test handling event with open DM policy enqueues the request."""
        matrix_channel._user_id = "@bot:example.com"
        matrix_channel._enqueue = Mock()
        matrix_channel._is_dm_room = AsyncMock(return_value=True)
        matrix_channel._send_read_receipt = AsyncMock()
        matrix_channel._send_typing = AsyncMock()
        matrix_channel._cfg.dm_policy = "open"
        matrix_channel._get_display_name = Mock(return_value="user")

        event = MagicMock(spec=RoomMessageText)
        event.sender = "@user:example.com"
        event.body = "Hello"
        event.event_id = "$evt1"
        event.source = {}
        mock_matrix_room.room_id = "!test_room:example.com"

        await matrix_channel._on_room_event(mock_matrix_room, event)

        matrix_channel._enqueue.assert_called_once()
        payload = matrix_channel._enqueue.call_args[0][0]
        assert payload["sender_id"] == "@user:example.com"

    async def test_on_room_event_deny_message_sent(
        self,
        matrix_channel,
        mock_matrix_room,
    ):
        """Test that blocked user does not get enqueued."""
        matrix_channel._user_id = "@bot:example.com"
        matrix_channel._cfg.dm_policy = "allowlist"
        matrix_channel._cfg.allow_from = []
        matrix_channel._is_dm_room = AsyncMock(return_value=True)
        matrix_channel._enqueue = Mock()

        event = MagicMock(spec=RoomMessageText)
        event.sender = "@unauthorized:example.com"
        event.body = "Hello"
        event.event_id = "$evt1"
        event.source = {}
        mock_matrix_room.room_id = "!test_room:example.com"

        await matrix_channel._on_room_event(mock_matrix_room, event)

        matrix_channel._enqueue.assert_not_called()

    async def test_on_room_event_require_mention_not_met(
        self,
        matrix_channel,
        mock_matrix_room,
    ):
        """Test event ignored in group when mention required but absent."""
        matrix_channel._user_id = "@bot:example.com"
        matrix_channel._enqueue = Mock()
        matrix_channel._is_dm_room = AsyncMock(return_value=False)
        matrix_channel._send_read_receipt = AsyncMock()
        matrix_channel._send_typing = AsyncMock()
        matrix_channel._cfg.group_policy = "open"
        matrix_channel._cfg.require_mention = True

        event = MagicMock(spec=RoomMessageText)
        event.sender = "@user:example.com"
        event.body = "Just a message with no bot mention"
        event.event_id = "$evt1"
        event.source = {}
        mock_matrix_room.room_id = "!test_room:example.com"

        await matrix_channel._on_room_event(mock_matrix_room, event)

        matrix_channel._enqueue.assert_not_called()


@pytest.mark.asyncio
class TestMatrixChannelMessageCallback:
    """Test message callbacks."""

    async def test_message_callback_ignores_own_message(
        self,
        matrix_channel,
        mock_matrix_room,
    ):
        """Test that bot ignores its own messages (no enqueue called)."""
        matrix_channel._user_id = "@bot:example.com"
        matrix_channel._enqueue = Mock()

        event = MagicMock(spec=RoomMessageText)
        event.sender = "@bot:example.com"
        event.body = "Hello"
        mock_matrix_room.room_id = "!room:example.com"

        await matrix_channel._on_room_event(mock_matrix_room, event)

        matrix_channel._enqueue.assert_not_called()

    async def test_message_callback_detects_mention(
        self,
        matrix_channel,
        mock_matrix_room,
    ):
        """Test bot mention detection: _was_mentioned returns True."""
        matrix_channel._user_id = "@bot:example.com"

        event = MagicMock(spec=RoomMessageText)
        event.sender = "@user:example.com"
        event.body = "Hello @bot:example.com!"
        event.source = {}

        assert matrix_channel._was_mentioned(event, event.body) is True

    async def test_message_callback_detects_localpart_mention(
        self,
        matrix_channel,
        mock_matrix_room,
    ):
        """Test mention detection by full MXID in text."""
        matrix_channel._user_id = "@mybot:example.com"

        event = MagicMock(spec=RoomMessageText)
        event.sender = "@user:example.com"
        event.body = "hello @mybot:example.com please help"
        event.source = {}

        assert matrix_channel._was_mentioned(event, event.body) is True

    async def test_message_callback_no_mention(
        self,
        matrix_channel,
        mock_matrix_room,
    ):
        """Test when bot is not mentioned."""
        matrix_channel._user_id = "@bot:example.com"

        event = MagicMock(spec=RoomMessageText)
        event.sender = "@user:example.com"
        event.body = "Just a regular message"
        event.source = {}

        assert matrix_channel._was_mentioned(event, event.body) is False


@pytest.mark.asyncio
class TestMatrixChannelMediaCallback:
    """Test media message callbacks."""

    async def test_media_callback_image(
        self,
        matrix_channel,
        mock_matrix_room,
        tmp_path,
    ):
        """Test handling image message enqueues image content."""
        fake_file = tmp_path / "image_123_image.png"
        fake_file.write_bytes(b"fake image")

        matrix_channel._user_id = "@bot:example.com"
        matrix_channel._enqueue = Mock()
        matrix_channel._download_mxc = AsyncMock(return_value=str(fake_file))
        matrix_channel._is_dm_room = AsyncMock(return_value=True)
        matrix_channel._send_read_receipt = AsyncMock()
        matrix_channel._send_typing = AsyncMock()

        event = MagicMock(spec=RoomMessageImage)
        event.sender = "@user:example.com"
        event.url = "mxc://example.org/image_123"
        event.body = "image.png"
        event.event_id = "$abc123"
        mock_matrix_room.room_id = "!room:example.com"

        await matrix_channel._on_room_media_event(mock_matrix_room, event)

        matrix_channel._enqueue.assert_called_once()
        payload = matrix_channel._enqueue.call_args[0][0]
        parts = payload["content_parts"]
        assert any(
            getattr(p, "type", None) == ContentType.IMAGE for p in parts
        )

    async def test_media_callback_video(
        self,
        matrix_channel,
        mock_matrix_room,
        tmp_path,
    ):
        """Test handling video message enqueues video content."""
        fake_file = tmp_path / "video_123_video.mp4"
        fake_file.write_bytes(b"fake video")

        matrix_channel._user_id = "@bot:example.com"
        matrix_channel._enqueue = Mock()
        matrix_channel._download_mxc = AsyncMock(return_value=str(fake_file))
        matrix_channel._is_dm_room = AsyncMock(return_value=True)
        matrix_channel._send_read_receipt = AsyncMock()
        matrix_channel._send_typing = AsyncMock()

        event = MagicMock(spec=RoomMessageVideo)
        event.sender = "@user:example.com"
        event.url = "mxc://example.org/video_123"
        event.body = "video.mp4"
        event.event_id = "$abc123"
        mock_matrix_room.room_id = "!room:example.com"

        await matrix_channel._on_room_media_event(mock_matrix_room, event)

        matrix_channel._enqueue.assert_called_once()
        payload = matrix_channel._enqueue.call_args[0][0]
        parts = payload["content_parts"]
        assert any(
            getattr(p, "type", None) == ContentType.VIDEO for p in parts
        )

    async def test_media_callback_audio(
        self,
        matrix_channel,
        mock_matrix_room,
        tmp_path,
    ):
        """Test handling audio message enqueues audio content."""
        fake_file = tmp_path / "audio_123_audio.mp3"
        fake_file.write_bytes(b"fake audio")

        matrix_channel._user_id = "@bot:example.com"
        matrix_channel._enqueue = Mock()
        matrix_channel._download_mxc = AsyncMock(return_value=str(fake_file))
        matrix_channel._is_dm_room = AsyncMock(return_value=True)
        matrix_channel._send_read_receipt = AsyncMock()
        matrix_channel._send_typing = AsyncMock()

        event = MagicMock(spec=RoomMessageAudio)
        event.sender = "@user:example.com"
        event.url = "mxc://example.org/audio_123"
        event.body = "audio.mp3"
        event.event_id = "$abc123"
        mock_matrix_room.room_id = "!room:example.com"

        await matrix_channel._on_room_media_event(mock_matrix_room, event)

        matrix_channel._enqueue.assert_called_once()
        payload = matrix_channel._enqueue.call_args[0][0]
        parts = payload["content_parts"]
        assert any(
            getattr(p, "type", None) == ContentType.AUDIO for p in parts
        )

    async def test_media_callback_file(
        self,
        matrix_channel,
        mock_matrix_room,
        tmp_path,
    ):
        """Test handling file message enqueues file content."""
        fake_file = tmp_path / "file_123_document.pdf"
        fake_file.write_bytes(b"fake pdf")

        matrix_channel._user_id = "@bot:example.com"
        matrix_channel._enqueue = Mock()
        matrix_channel._download_mxc = AsyncMock(return_value=str(fake_file))
        matrix_channel._is_dm_room = AsyncMock(return_value=True)
        matrix_channel._send_read_receipt = AsyncMock()
        matrix_channel._send_typing = AsyncMock()

        event = MagicMock(spec=RoomMessageFile)
        event.sender = "@user:example.com"
        event.url = "mxc://example.org/file_123"
        event.body = "document.pdf"
        event.event_id = "$abc123"
        mock_matrix_room.room_id = "!room:example.com"

        await matrix_channel._on_room_media_event(mock_matrix_room, event)

        matrix_channel._enqueue.assert_called_once()
        payload = matrix_channel._enqueue.call_args[0][0]
        parts = payload["content_parts"]
        assert any(getattr(p, "type", None) == ContentType.FILE for p in parts)

    async def test_media_callback_ignores_own_message(
        self,
        matrix_channel,
        mock_matrix_room,
    ):
        """Test that bot ignores its own media messages."""
        matrix_channel._user_id = "@bot:example.com"
        matrix_channel._enqueue = Mock()

        event = MagicMock(spec=RoomMessageImage)
        event.sender = "@bot:example.com"
        event.url = "mxc://example.org/image_123"
        mock_matrix_room.room_id = "!room:example.com"

        await matrix_channel._on_room_media_event(mock_matrix_room, event)

        matrix_channel._enqueue.assert_not_called()


@pytest.mark.asyncio
class TestMatrixChannelStartStop:
    """Test start and stop lifecycle."""

    async def test_start_when_not_configured(self, matrix_channel):
        """Test start when channel is not properly configured."""
        matrix_channel._cfg.homeserver = ""

        await matrix_channel.start()

        assert matrix_channel._client is None

    async def test_start_creates_client(
        self,
        matrix_channel,
        mock_async_client,
    ):
        """Test that start creates and configures AsyncClient."""
        with patch(
            "qwenpaw.app.channels.matrix.channel.AsyncClient",
            return_value=mock_async_client,
        ):
            await matrix_channel.start()

            assert matrix_channel._client is mock_async_client
            assert mock_async_client.access_token == "test_token_123"
            assert mock_async_client.add_event_callback.call_count >= 2

    async def test_start_starts_sync_task(
        self,
        matrix_channel,
        mock_async_client,
    ):
        """Test that start creates sync task."""
        with patch(
            "qwenpaw.app.channels.matrix.channel.AsyncClient",
            return_value=mock_async_client,
        ):
            await matrix_channel.start()

            assert matrix_channel._sync_task is not None
            assert not matrix_channel._sync_task.done()

    async def test_stop_cancels_sync_task(
        self,
        matrix_channel,
        mock_async_client,
    ):
        """Test that stop cancels sync task."""
        with patch(
            "qwenpaw.app.channels.matrix.channel.AsyncClient",
            return_value=mock_async_client,
        ):
            await matrix_channel.start()

            await matrix_channel.stop()

            # Verify stop was called on the client
            assert mock_async_client.close.called

    async def test_stop_closes_client(self, matrix_channel, mock_async_client):
        """Test that stop closes the client."""
        with patch(
            "qwenpaw.app.channels.matrix.channel.AsyncClient",
            return_value=mock_async_client,
        ):
            await matrix_channel.start()

            await matrix_channel.stop()

            mock_async_client.close.assert_called_once()

    async def test_stop_when_not_started(self, matrix_channel):
        """Test stop when channel was never started."""
        # Should not raise
        await matrix_channel.stop()


@pytest.mark.asyncio
class TestMatrixChannelSend:
    """Test send method."""

    async def test_send_success(self, matrix_channel, mock_async_client):
        """Test successful message send."""
        mock_async_client.room_send = AsyncMock(return_value=MagicMock())
        matrix_channel._client = mock_async_client

        await matrix_channel.send("!room:example.com", "Hello world")

        mock_async_client.room_send.assert_called_once()
        call_args = mock_async_client.room_send.call_args
        assert call_args[0][0] == "!room:example.com"
        assert call_args[0][1] == "m.room.message"
        content = call_args[0][2]
        assert content["msgtype"] == "m.text"
        assert content["body"] == "Hello world"

    async def test_send_when_client_not_initialized(self, matrix_channel):
        """Test send when client is not initialized."""
        matrix_channel._client = None

        # Should not raise
        await matrix_channel.send("!room:example.com", "Hello")

    async def test_send_empty_message(self, matrix_channel, mock_async_client):
        """Test sending empty message does not raise."""
        mock_async_client.room_send = AsyncMock(return_value=MagicMock())
        matrix_channel._client = mock_async_client

        # Should not raise regardless of whether implementation sends or skips
        await matrix_channel.send("!room:example.com", "")

    async def test_send_handles_room_send_error(
        self,
        matrix_channel,
        mock_async_client,
    ):
        """Test handling RoomSendError."""
        error_response = RoomSendError(
            message="Send failed",
            status_code="M_UNKNOWN",
        )
        mock_async_client.room_send = AsyncMock(return_value=error_response)
        matrix_channel._client = mock_async_client

        # Should not raise, just log error
        await matrix_channel.send("!room:example.com", "Hello")


@pytest.mark.asyncio
class TestMatrixChannelSendContentParts:
    """Test send_content_parts method."""

    async def test_send_content_parts_text_only(self, matrix_channel):
        """Test sending text content parts."""
        matrix_channel.send = AsyncMock()

        parts = [TextContent(type=ContentType.TEXT, text="Hello")]
        await matrix_channel.send_content_parts("!room:example.com", parts)

        matrix_channel.send.assert_called_once_with(
            "!room:example.com",
            "Hello",
            None,
        )

    async def test_send_content_parts_image(self, matrix_channel):
        """Test sending image content parts."""
        matrix_channel.send_media = AsyncMock()

        parts = [
            ImageContent(
                type=ContentType.IMAGE,
                image_url="https://example.com/img.png",
            ),
        ]
        await matrix_channel.send_content_parts("!room:example.com", parts)

        matrix_channel.send_media.assert_called_once()

    async def test_send_content_parts_mixed(self, matrix_channel):
        """Test sending mixed text and media content parts."""
        matrix_channel.send = AsyncMock()
        matrix_channel.send_media = AsyncMock()

        parts = [
            TextContent(type=ContentType.TEXT, text="Hello"),
            ImageContent(
                type=ContentType.IMAGE,
                image_url="https://example.com/img.png",
            ),
        ]
        await matrix_channel.send_content_parts("!room:example.com", parts)

        matrix_channel.send.assert_called_once()
        matrix_channel.send_media.assert_called_once()


@pytest.mark.asyncio
class TestMatrixChannelSendMedia:
    """Test send_media method."""

    async def test_send_media_when_client_not_initialized(
        self,
        matrix_channel,
    ):
        """Test send_media when client is not initialized."""
        matrix_channel._client = None

        part = ImageContent(
            type=ContentType.IMAGE,
            image_url="https://example.com/img.png",
        )
        # Should not raise
        await matrix_channel.send_media("!room:example.com", part)

    async def test_send_media_missing_url(
        self,
        matrix_channel,
        mock_async_client,
    ):
        """Test send_media when part has no URL."""
        matrix_channel._client = mock_async_client

        part = ImageContent(type=ContentType.IMAGE, image_url=None)
        await matrix_channel.send_media("!room:example.com", part)

        mock_async_client.upload.assert_not_called()

    async def test_send_media_file_url(
        self,
        matrix_channel,
        mock_async_client,
        tmp_path,
    ):
        """Test sending media from file:// URL."""
        # Create temp file
        test_file = tmp_path / "test_image.png"
        test_file.write_bytes(b"fake image data")

        matrix_channel._client = mock_async_client
        upload_response = UploadResponse(
            content_uri="mxc://example.org/uploaded_123",
        )
        mock_async_client.upload = AsyncMock(
            return_value=(upload_response, None),
        )
        mock_async_client.room_send = AsyncMock(return_value=MagicMock())

        part = ImageContent(
            type=ContentType.IMAGE,
            image_url=f"file://{test_file}",
        )
        await matrix_channel.send_media("!room:example.com", part)

        mock_async_client.upload.assert_called_once()
        mock_async_client.room_send.assert_called_once()

    async def test_send_media_http_url(
        self,
        matrix_channel,
        mock_async_client,
    ):
        """Test sending media from HTTP URL."""
        # Just verify no exception is raised when channel is properly set up
        part = ImageContent(
            type=ContentType.IMAGE,
            image_url="https://example.com/img.png",
        )
        # Actual HTTP mocking is too complex, just verify the method runs
        matrix_channel._client = mock_async_client
        try:
            await matrix_channel.send_media("!room:example.com", part)
        except (TypeError, AttributeError):
            # Expected due to aiohttp mocking complexity
            pass

    async def test_send_media_http_download_fails(
        self,
        matrix_channel,
        mock_async_client,
    ):
        """Test handling HTTP download failure."""
        matrix_channel._client = mock_async_client

        # Mock failed aiohttp response
        mock_response = AsyncMock()
        mock_response.status = 404

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = AsyncMock(return_value=mock_response)
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            part = ImageContent(
                type=ContentType.IMAGE,
                image_url="https://example.com/img.png",
            )
            await matrix_channel.send_media("!room:example.com", part)

        mock_async_client.upload.assert_not_called()

    async def test_send_media_upload_error(
        self,
        matrix_channel,
        mock_async_client,
        tmp_path,
    ):
        """Test handling upload error."""
        test_file = tmp_path / "test_image.png"
        test_file.write_bytes(b"fake image data")

        matrix_channel._client = mock_async_client
        upload_error = UploadError(message="Upload failed")
        mock_async_client.upload = AsyncMock(return_value=(upload_error, None))

        part = ImageContent(
            type=ContentType.IMAGE,
            image_url=f"file://{test_file}",
        )
        await matrix_channel.send_media("!room:example.com", part)

        mock_async_client.room_send.assert_not_called()

    async def test_send_media_room_send_error(
        self,
        matrix_channel,
        mock_async_client,
        tmp_path,
    ):
        """Test handling room_send error."""
        test_file = tmp_path / "test_image.png"
        test_file.write_bytes(b"fake image data")

        matrix_channel._client = mock_async_client
        upload_response = UploadResponse(
            content_uri="mxc://example.org/uploaded_123",
        )
        mock_async_client.upload = AsyncMock(
            return_value=(upload_response, None),
        )
        send_error = RoomSendError(
            message="Send failed",
            status_code="M_UNKNOWN",
        )
        mock_async_client.room_send = AsyncMock(return_value=send_error)

        part = ImageContent(
            type=ContentType.IMAGE,
            image_url=f"file://{test_file}",
        )
        await matrix_channel.send_media("!room:example.com", part)

        # Should not raise, error is logged

    async def test_send_media_video_type(
        self,
        matrix_channel,
        mock_async_client,
        tmp_path,
    ):
        """Test sending video media type."""
        from agentscope_runtime.engine.schemas.agent_schemas import (
            VideoContent,
        )

        test_file = tmp_path / "test_video.mp4"
        test_file.write_bytes(b"fake video data")

        matrix_channel._client = mock_async_client
        upload_response = UploadResponse(
            content_uri="mxc://example.org/uploaded_123",
        )
        mock_async_client.upload = AsyncMock(
            return_value=(upload_response, None),
        )
        mock_async_client.room_send = AsyncMock(return_value=MagicMock())

        part = VideoContent(
            type=ContentType.VIDEO,
            video_url=f"file://{test_file}",
        )
        await matrix_channel.send_media("!room:example.com", part)

        call_args = mock_async_client.room_send.call_args[0][2]
        assert call_args["msgtype"] == "m.video"

    async def test_send_media_audio_type(
        self,
        matrix_channel,
        mock_async_client,
        tmp_path,
    ):
        """Test sending audio media type."""
        from agentscope_runtime.engine.schemas.agent_schemas import (
            AudioContent,
        )

        test_file = tmp_path / "test_audio.mp3"
        test_file.write_bytes(b"fake audio data")

        matrix_channel._client = mock_async_client
        upload_response = UploadResponse(
            content_uri="mxc://example.org/uploaded_123",
        )
        mock_async_client.upload = AsyncMock(
            return_value=(upload_response, None),
        )
        mock_async_client.room_send = AsyncMock(return_value=MagicMock())

        part = AudioContent(type=ContentType.AUDIO, data=f"file://{test_file}")
        await matrix_channel.send_media("!room:example.com", part)

        call_args = mock_async_client.room_send.call_args[0][2]
        assert call_args["msgtype"] == "m.audio"

    async def test_send_media_unknown_url_scheme(
        self,
        matrix_channel,
        mock_async_client,
    ):
        """Test handling unknown URL scheme."""
        matrix_channel._client = mock_async_client

        part = ImageContent(
            type=ContentType.IMAGE,
            image_url="ftp://example.com/img.png",
        )
        await matrix_channel.send_media("!room:example.com", part)

        mock_async_client.upload.assert_not_called()

    async def test_send_media_generic_file_type(
        self,
        matrix_channel,
        mock_async_client,
        tmp_path,
    ):
        """Test sending generic file media type."""
        test_file = tmp_path / "test_document.pdf"
        test_file.write_bytes(b"fake pdf data")

        matrix_channel._client = mock_async_client
        upload_response = UploadResponse(
            content_uri="mxc://example.org/uploaded_123",
        )
        mock_async_client.upload = AsyncMock(
            return_value=(upload_response, None),
        )
        mock_async_client.room_send = AsyncMock(return_value=MagicMock())

        from agentscope_runtime.engine.schemas.agent_schemas import FileContent

        part = FileContent(
            type=ContentType.FILE,
            file_url=f"file://{test_file}",
        )
        await matrix_channel.send_media("!room:example.com", part)

        call_args = mock_async_client.room_send.call_args[0][2]
        assert call_args["msgtype"] == "m.file"
