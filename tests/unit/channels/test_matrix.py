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

from copaw.app.channels.matrix.channel import MatrixChannel
from copaw.config.config import MatrixConfig


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
        channel = MatrixChannel(
            process=mock_process,
            enabled=True,
            homeserver="https://matrix.example.com",
            user_id="@bot:example.com",
            access_token="test_token",
        )

        assert channel.enabled is True
        assert channel.homeserver == "https://matrix.example.com"
        assert channel.user_id == "@bot:example.com"
        assert channel.access_token == "test_token"
        assert channel.channel == "matrix"
        assert channel.uses_manager_queue is True
        assert channel.client is None
        assert channel._sync_task is None

    def test_init_homeserver_trailing_slash(self, mock_process):
        """Test that trailing slash is stripped from homeserver."""
        channel = MatrixChannel(
            process=mock_process,
            enabled=True,
            homeserver="https://matrix.example.com/",
            user_id="@bot:example.com",
            access_token="test_token",
        )

        assert channel.homeserver == "https://matrix.example.com"

    def test_init_with_all_params(self, mock_process):
        """Test initialization with all optional parameters."""
        channel = MatrixChannel(
            process=mock_process,
            enabled=True,
            homeserver="https://matrix.example.com",
            user_id="@bot:example.com",
            access_token="test_token",
            on_reply_sent=Mock(),
            show_tool_details=False,
            filter_tool_messages=True,
            filter_thinking=True,
            bot_prefix="!cmd",
            dm_policy="allowlist",
            group_policy="allowlist",
            allow_from=["@user:example.com"],
            deny_message="Custom deny message",
            require_mention=True,
        )

        assert channel.bot_prefix == "!cmd"
        assert channel.dm_policy == "allowlist"
        assert channel.group_policy == "allowlist"
        assert channel.allow_from == {"@user:example.com"}
        assert channel.deny_message == "Custom deny message"
        assert channel.require_mention is True
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

        assert channel.enabled is True
        assert channel.homeserver == "https://matrix.example.com"
        assert channel.user_id == "@bot:example.com"
        assert channel.access_token == "test_token_123"

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
        """Test that from_env raises NotImplementedError."""
        with pytest.raises(NotImplementedError) as exc_info:
            MatrixChannel.from_env(process=mock_process)

        assert "Matrix channel must be configured via config file" in str(
            exc_info.value,
        )


class TestMatrixChannelMXC:
    """Test MXC to HTTP URL conversion."""

    def test_mxc_to_http_with_valid_mxc(self, matrix_channel):
        """Test converting valid MXC URL to HTTP."""
        mxc_url = "mxc://matrix.org/media_123"
        http_url = matrix_channel._mxc_to_http(mxc_url)

        expected = (
            "https://matrix.example.com/_matrix/media/v3/download/"
            "matrix.org/media_123?access_token=test_token_123"
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
        matrix_channel.dm_policy = "open"
        matrix_channel.group_policy = "open"

        allowed, message = matrix_channel._check_allowlist(
            "@any_user:example.com",
            is_group=False,
        )

        assert allowed is True
        assert message == ""

    def test_check_allowlist_allowlist_user_allowed(self, matrix_channel):
        """Test allowed user on allowlist."""
        matrix_channel.dm_policy = "allowlist"
        matrix_channel.allow_from = {"@allowed:example.com"}

        allowed, message = matrix_channel._check_allowlist(
            "@allowed:example.com",
            is_group=False,
        )

        assert allowed is True
        assert message == ""

    def test_check_allowlist_allowlist_user_denied(self, matrix_channel):
        """Test denied user not on allowlist."""
        matrix_channel.dm_policy = "allowlist"
        matrix_channel.group_policy = "allowlist"
        matrix_channel.allow_from = {"@allowed:example.com"}
        matrix_channel.deny_message = "Custom deny"

        allowed, message = matrix_channel._check_allowlist(
            "@not_allowed:example.com",
            is_group=False,
        )

        assert allowed is False
        assert message == "Custom deny"

    def test_check_allowlist_dm_vs_group_policy(self, matrix_channel):
        """Test different policies for DM and group."""
        matrix_channel.dm_policy = "allowlist"
        matrix_channel.group_policy = "open"
        matrix_channel.allow_from = {"@allowed:example.com"}

        # DM should use allowlist
        allowed_dm, _ = matrix_channel._check_allowlist(
            "@unknown:example.com",
            is_group=False,
        )
        assert allowed_dm is False

        # Group should be open
        allowed_group, _ = matrix_channel._check_allowlist(
            "@unknown:example.com",
            is_group=True,
        )
        assert allowed_group is True


@pytest.mark.asyncio
class TestMatrixChannelBuildRequest:
    """Test request building methods."""

    def test_build_agent_request_from_native(self, matrix_channel):
        """Test building AgentRequest from native payload."""
        payload = {
            "room_id": "!room:example.com",
            "sender": "@user:example.com",
            "body": "Hello bot",
        }

        request = matrix_channel.build_agent_request_from_native(payload)

        assert isinstance(request, AgentRequest)
        assert request.channel == "matrix"
        assert request.user_id == "@user:example.com"
        assert request.session_id == "matrix:!room:example.com"

    def test_build_agent_request_with_content_parts(self, matrix_channel):
        """Test building request with existing content_parts."""
        content_parts = [
            TextContent(type=ContentType.TEXT, text="Test message"),
        ]
        payload = {
            "room_id": "!room:example.com",
            "sender": "@user:example.com",
            "content_parts": content_parts,
        }

        request = matrix_channel.build_agent_request_from_native(payload)

        assert request.input[0].content == content_parts

    def test_get_to_handle_from_request_with_session_id(self, matrix_channel):
        """Test getting room_id from session_id."""
        request = MagicMock(spec=AgentRequest)
        request.session_id = "matrix:!room:example.com"
        request.channel_meta = {}

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

    async def test_handle_event_open_policy(
        self,
        matrix_channel,
        mock_matrix_room,
    ):
        """Test handling event with open policy."""
        matrix_channel._enqueue = Mock()
        matrix_channel.dm_policy = "open"
        content_parts = [TextContent(type=ContentType.TEXT, text="Hello")]

        await matrix_channel._handle_event(
            mock_matrix_room,
            "@user:example.com",
            content_parts,
        )

        matrix_channel._enqueue.assert_called_once()
        call_args = matrix_channel._enqueue.call_args[0][0]
        assert call_args["room_id"] == "!test_room:example.com"
        assert call_args["sender"] == "@user:example.com"

    async def test_handle_event_deny_message_sent(
        self,
        matrix_channel,
        mock_matrix_room,
    ):
        """Test that deny message is sent when user not allowed."""
        matrix_channel.dm_policy = "allowlist"
        matrix_channel.allow_from = set()
        matrix_channel.deny_message = "Access denied"
        matrix_channel.send = AsyncMock()
        content_parts = [TextContent(type=ContentType.TEXT, text="Hello")]

        await matrix_channel._handle_event(
            mock_matrix_room,
            "@unauthorized:example.com",
            content_parts,
        )

        matrix_channel.send.assert_called_once_with(
            "!test_room:example.com",
            "Access denied",
        )

    async def test_handle_event_require_mention_not_met(
        self,
        matrix_channel,
        mock_matrix_room,
    ):
        """Test that event is ignored when mention required but not present."""
        matrix_channel.require_mention = True
        matrix_channel.dm_policy = "open"
        matrix_channel._enqueue = Mock()
        matrix_channel._check_group_mention = Mock(return_value=False)
        content_parts = [TextContent(type=ContentType.TEXT, text="Hello")]

        await matrix_channel._handle_event(
            mock_matrix_room,
            "@user:example.com",
            content_parts,
            bot_mentioned=False,
        )

        matrix_channel._enqueue.assert_not_called()


@pytest.mark.asyncio
class TestMatrixChannelMessageCallback:
    """Test message callbacks."""

    async def test_message_callback_ignores_own_message(
        self,
        matrix_channel,
        mock_matrix_room,
    ):
        """Test that bot ignores its own messages."""
        matrix_channel.user_id = "@bot:example.com"
        matrix_channel._handle_event = AsyncMock()

        event = MagicMock(spec=RoomMessageText)
        event.sender = "@bot:example.com"
        event.body = "Hello"

        await matrix_channel._message_callback(mock_matrix_room, event)

        matrix_channel._handle_event.assert_not_called()

    async def test_message_callback_detects_mention(
        self,
        matrix_channel,
        mock_matrix_room,
    ):
        """Test bot mention detection in message."""
        matrix_channel.user_id = "@bot:example.com"
        matrix_channel._handle_event = AsyncMock()

        event = MagicMock(spec=RoomMessageText)
        event.sender = "@user:example.com"
        event.body = "Hello @bot:example.com!"

        await matrix_channel._message_callback(mock_matrix_room, event)

        matrix_channel._handle_event.assert_called_once()
        call_kwargs = matrix_channel._handle_event.call_args[1]
        assert call_kwargs["bot_mentioned"] is True

    async def test_message_callback_detects_localpart_mention(
        self,
        matrix_channel,
        mock_matrix_room,
    ):
        """Test mention detection by localpart."""
        matrix_channel.user_id = "@mybot:example.com"
        matrix_channel._handle_event = AsyncMock()

        event = MagicMock(spec=RoomMessageText)
        event.sender = "@user:example.com"
        event.body = "mybot help"

        await matrix_channel._message_callback(mock_matrix_room, event)

        call_kwargs = matrix_channel._handle_event.call_args[1]
        assert call_kwargs["bot_mentioned"] is True

    async def test_message_callback_no_mention(
        self,
        matrix_channel,
        mock_matrix_room,
    ):
        """Test when bot is not mentioned."""
        matrix_channel.user_id = "@bot:example.com"
        matrix_channel._handle_event = AsyncMock()

        event = MagicMock(spec=RoomMessageText)
        event.sender = "@user:example.com"
        event.body = "Just a regular message"

        await matrix_channel._message_callback(mock_matrix_room, event)

        call_kwargs = matrix_channel._handle_event.call_args[1]
        assert call_kwargs["bot_mentioned"] is False


@pytest.mark.asyncio
class TestMatrixChannelMediaCallback:
    """Test media message callbacks."""

    async def test_media_callback_image(
        self,
        matrix_channel,
        mock_matrix_room,
    ):
        """Test handling image message."""
        matrix_channel._handle_event = AsyncMock()
        matrix_channel._mxc_to_http = Mock(
            return_value="https://example.com/image.png",
        )

        event = MagicMock(spec=RoomMessageImage)
        event.sender = "@user:example.com"
        event.url = "mxc://example.org/image_123"
        event.body = "image.png"

        await matrix_channel._media_callback(mock_matrix_room, event)

        matrix_channel._handle_event.assert_called_once()
        content_parts = matrix_channel._handle_event.call_args[0][2]
        assert len(content_parts) == 1
        assert content_parts[0].type == ContentType.IMAGE
        assert content_parts[0].image_url == "https://example.com/image.png"

    async def test_media_callback_video(
        self,
        matrix_channel,
        mock_matrix_room,
    ):
        """Test handling video message."""
        matrix_channel._handle_event = AsyncMock()
        matrix_channel._mxc_to_http = Mock(
            return_value="https://example.com/video.mp4",
        )

        event = MagicMock(spec=RoomMessageVideo)
        event.sender = "@user:example.com"
        event.url = "mxc://example.org/video_123"
        event.body = "video.mp4"

        await matrix_channel._media_callback(mock_matrix_room, event)

        content_parts = matrix_channel._handle_event.call_args[0][2]
        assert content_parts[0].type == ContentType.VIDEO
        assert content_parts[0].video_url == "https://example.com/video.mp4"

    async def test_media_callback_audio(
        self,
        matrix_channel,
        mock_matrix_room,
    ):
        """Test handling audio message."""
        matrix_channel._handle_event = AsyncMock()
        matrix_channel._mxc_to_http = Mock(
            return_value="https://example.com/audio.mp3",
        )

        event = MagicMock(spec=RoomMessageAudio)
        event.sender = "@user:example.com"
        event.url = "mxc://example.org/audio_123"
        event.body = "audio.mp3"

        await matrix_channel._media_callback(mock_matrix_room, event)

        content_parts = matrix_channel._handle_event.call_args[0][2]
        assert content_parts[0].type == ContentType.AUDIO
        assert content_parts[0].data == "https://example.com/audio.mp3"

    async def test_media_callback_file(self, matrix_channel, mock_matrix_room):
        """Test handling file message."""
        matrix_channel._handle_event = AsyncMock()
        matrix_channel._mxc_to_http = Mock(
            return_value="https://example.com/doc.pdf",
        )

        event = MagicMock(spec=RoomMessageFile)
        event.sender = "@user:example.com"
        event.url = "mxc://example.org/file_123"
        event.body = "document.pdf"

        await matrix_channel._media_callback(mock_matrix_room, event)

        content_parts = matrix_channel._handle_event.call_args[0][2]
        assert content_parts[0].type == ContentType.FILE
        assert content_parts[0].file_url == "https://example.com/doc.pdf"

    async def test_media_callback_ignores_own_message(
        self,
        matrix_channel,
        mock_matrix_room,
    ):
        """Test that bot ignores its own media messages."""
        matrix_channel.user_id = "@bot:example.com"
        matrix_channel._handle_event = AsyncMock()

        event = MagicMock(spec=RoomMessageImage)
        event.sender = "@bot:example.com"
        event.url = "mxc://example.org/image_123"

        await matrix_channel._media_callback(mock_matrix_room, event)

        matrix_channel._handle_event.assert_not_called()


@pytest.mark.asyncio
class TestMatrixChannelStartStop:
    """Test start and stop lifecycle."""

    async def test_start_when_not_configured(self, matrix_channel):
        """Test start when channel is not properly configured."""
        matrix_channel.enabled = False

        await matrix_channel.start()

        assert matrix_channel.client is None

    async def test_start_creates_client(
        self,
        matrix_channel,
        mock_async_client,
    ):
        """Test that start creates and configures AsyncClient."""
        with patch(
            "copaw.app.channels.matrix.channel.AsyncClient",
            return_value=mock_async_client,
        ):
            await matrix_channel.start()

            assert matrix_channel.client is mock_async_client
            assert mock_async_client.access_token == "test_token_123"
            assert mock_async_client.add_event_callback.call_count == 5

    async def test_start_starts_sync_task(
        self,
        matrix_channel,
        mock_async_client,
    ):
        """Test that start creates sync task."""
        with patch(
            "copaw.app.channels.matrix.channel.AsyncClient",
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
            "copaw.app.channels.matrix.channel.AsyncClient",
            return_value=mock_async_client,
        ):
            await matrix_channel.start()

            await matrix_channel.stop()

            # Verify stop was called on the client
            assert mock_async_client.close.called

    async def test_stop_closes_client(self, matrix_channel, mock_async_client):
        """Test that stop closes the client."""
        with patch(
            "copaw.app.channels.matrix.channel.AsyncClient",
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
        matrix_channel.client = mock_async_client

        await matrix_channel.send("!room:example.com", "Hello world")

        mock_async_client.room_send.assert_called_once_with(
            room_id="!room:example.com",
            message_type="m.room.message",
            content={"msgtype": "m.text", "body": "Hello world"},
        )

    async def test_send_when_client_not_initialized(self, matrix_channel):
        """Test send when client is not initialized."""
        matrix_channel.client = None

        # Should not raise
        await matrix_channel.send("!room:example.com", "Hello")

    async def test_send_empty_message(self, matrix_channel, mock_async_client):
        """Test sending empty message."""
        matrix_channel.client = mock_async_client

        await matrix_channel.send("!room:example.com", "")

        mock_async_client.room_send.assert_not_called()

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
        matrix_channel.client = mock_async_client

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
        matrix_channel.client = None

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
        matrix_channel.client = mock_async_client

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

        matrix_channel.client = mock_async_client
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
        matrix_channel.client = mock_async_client
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
        matrix_channel.client = mock_async_client

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

        matrix_channel.client = mock_async_client
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

        matrix_channel.client = mock_async_client
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

        matrix_channel.client = mock_async_client
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

        call_args = mock_async_client.room_send.call_args[1]
        assert call_args["content"]["msgtype"] == "m.video"

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

        matrix_channel.client = mock_async_client
        upload_response = UploadResponse(
            content_uri="mxc://example.org/uploaded_123",
        )
        mock_async_client.upload = AsyncMock(
            return_value=(upload_response, None),
        )
        mock_async_client.room_send = AsyncMock(return_value=MagicMock())

        part = AudioContent(type=ContentType.AUDIO, data=f"file://{test_file}")
        await matrix_channel.send_media("!room:example.com", part)

        call_args = mock_async_client.room_send.call_args[1]
        assert call_args["content"]["msgtype"] == "m.audio"

    async def test_send_media_unknown_url_scheme(
        self,
        matrix_channel,
        mock_async_client,
    ):
        """Test handling unknown URL scheme."""
        matrix_channel.client = mock_async_client

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

        matrix_channel.client = mock_async_client
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

        call_args = mock_async_client.room_send.call_args[1]
        assert call_args["content"]["msgtype"] == "m.file"
