"""Legacy ingress oracles mechanically moved to the async native admission seam.

The old synchronous queue fixture becomes an awaitable host-boundary observer;
all original payload/type/count/mute/self-filter assertions remain. These unit
cases retain their explicit SDK/download doubles; native HTTP cases complement
rather than relabel them as end-to-end evidence.
"""
from unittest.mock import AsyncMock, MagicMock, Mock
import pytest
from nio import RoomMessageAudio, RoomMessageFile, RoomMessageImage, RoomMessageText, RoomMessageVideo
from qwenpaw.schemas import ContentType
from matrix_pure_oracle_suite import matrix_channel, mock_matrix_room

@pytest.mark.asyncio
async def test_on_room_event_dm_not_disabled(
    matrix_channel,
    mock_matrix_room,
):
    """Test handling event with DM not disabled enqueues the request."""
    matrix_channel._user_id = "@bot:example.com"
    matrix_channel.on_event = AsyncMock(return_value=True)
    matrix_channel._is_dm_room = AsyncMock(return_value=True)
    matrix_channel._send_read_receipt = AsyncMock()
    matrix_channel._send_typing = AsyncMock()
    matrix_channel.dm_disabled = False
    matrix_channel._get_display_name = Mock(return_value="user")

    event = MagicMock(spec=RoomMessageText)
    event.sender = "@user:example.com"
    event.body = "Hello"
    event.event_id = "$evt1"
    event.source = {}
    mock_matrix_room.room_id = "!test_room:example.com"

    await matrix_channel._on_room_event(mock_matrix_room, event)

    matrix_channel.on_event.assert_called_once()
    payload = matrix_channel.on_event.call_args[0][0]
    assert payload["sender_id"] == "@user:example.com"


@pytest.mark.asyncio
async def test_on_room_event_dm_disabled(
    matrix_channel,
    mock_matrix_room,
):
    """Test that DM messages are dropped when dm_disabled=True."""
    matrix_channel._user_id = "@bot:example.com"
    matrix_channel.dm_disabled = True
    matrix_channel._is_dm_room = AsyncMock(return_value=True)
    matrix_channel.on_event = AsyncMock(return_value=True)

    event = MagicMock(spec=RoomMessageText)
    event.sender = "@unauthorized:example.com"
    event.body = "Hello"
    event.event_id = "$evt1"
    event.source = {}
    mock_matrix_room.room_id = "!test_room:example.com"

    await matrix_channel._on_room_event(mock_matrix_room, event)

    matrix_channel.on_event.assert_not_called()


@pytest.mark.asyncio
async def test_on_room_event_require_mention_not_met(
    matrix_channel,
    mock_matrix_room,
):
    """Test event ignored in group when mention required but absent."""
    matrix_channel._user_id = "@bot:example.com"
    matrix_channel.on_event = AsyncMock(return_value=True)
    matrix_channel._is_dm_room = AsyncMock(return_value=False)
    matrix_channel._send_read_receipt = AsyncMock()
    matrix_channel._send_typing = AsyncMock()
    matrix_channel.group_disabled = False
    matrix_channel.require_mention = True

    event = MagicMock(spec=RoomMessageText)
    event.sender = "@user:example.com"
    event.body = "Just a message with no bot mention"
    event.event_id = "$evt1"
    event.source = {}
    mock_matrix_room.room_id = "!test_room:example.com"

    await matrix_channel._on_room_event(mock_matrix_room, event)

    matrix_channel.on_event.assert_not_called()


@pytest.mark.asyncio
async def test_message_callback_ignores_own_message(
    matrix_channel,
    mock_matrix_room,
):
    """Test that bot ignores its own messages (no enqueue called)."""
    matrix_channel._user_id = "@bot:example.com"
    matrix_channel.on_event = AsyncMock(return_value=True)

    event = MagicMock(spec=RoomMessageText)
    event.sender = "@bot:example.com"
    event.body = "Hello"
    mock_matrix_room.room_id = "!room:example.com"

    await matrix_channel._on_room_event(mock_matrix_room, event)

    matrix_channel.on_event.assert_not_called()


@pytest.mark.asyncio
async def test_message_callback_no_mention(
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
async def test_media_callback_image(
    matrix_channel,
    mock_matrix_room,
    tmp_path,
):
    """Test handling image message enqueues image content."""
    fake_file = tmp_path / "image_123_image.png"
    fake_file.write_bytes(b"fake image")

    matrix_channel._user_id = "@bot:example.com"
    matrix_channel.vision_enabled = True
    matrix_channel.on_event = AsyncMock(return_value=True)
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

    matrix_channel.on_event.assert_called_once()
    payload = matrix_channel.on_event.call_args[0][0]
    parts = payload["content_parts"]
    assert any(
        getattr(p, "type", None) == ContentType.IMAGE for p in parts
    )


@pytest.mark.asyncio
async def test_media_callback_video(
    matrix_channel,
    mock_matrix_room,
    tmp_path,
):
    """Test handling video message enqueues video content."""
    fake_file = tmp_path / "video_123_video.mp4"
    fake_file.write_bytes(b"fake video")

    matrix_channel._user_id = "@bot:example.com"
    matrix_channel.on_event = AsyncMock(return_value=True)
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

    matrix_channel.on_event.assert_called_once()
    payload = matrix_channel.on_event.call_args[0][0]
    parts = payload["content_parts"]
    assert any(
        getattr(p, "type", None) == ContentType.VIDEO for p in parts
    )


@pytest.mark.asyncio
async def test_media_callback_audio(
    matrix_channel,
    mock_matrix_room,
    tmp_path,
):
    """Test handling audio message enqueues audio content."""
    fake_file = tmp_path / "audio_123_audio.mp3"
    fake_file.write_bytes(b"fake audio")

    matrix_channel._user_id = "@bot:example.com"
    matrix_channel.on_event = AsyncMock(return_value=True)
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

    matrix_channel.on_event.assert_called_once()
    payload = matrix_channel.on_event.call_args[0][0]
    parts = payload["content_parts"]
    assert any(
        getattr(p, "type", None) == ContentType.AUDIO for p in parts
    )


@pytest.mark.asyncio
async def test_media_callback_file(
    matrix_channel,
    mock_matrix_room,
    tmp_path,
):
    """Test handling file message enqueues file content."""
    fake_file = tmp_path / "file_123_document.pdf"
    fake_file.write_bytes(b"fake pdf")

    matrix_channel._user_id = "@bot:example.com"
    matrix_channel.on_event = AsyncMock(return_value=True)
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

    matrix_channel.on_event.assert_called_once()
    payload = matrix_channel.on_event.call_args[0][0]
    parts = payload["content_parts"]
    assert any(getattr(p, "type", None) == ContentType.FILE for p in parts)


@pytest.mark.asyncio
async def test_media_callback_ignores_own_message(
    matrix_channel,
    mock_matrix_room,
):
    """Test that bot ignores its own media messages."""
    matrix_channel._user_id = "@bot:example.com"
    matrix_channel.on_event = AsyncMock(return_value=True)

    event = MagicMock(spec=RoomMessageImage)
    event.sender = "@bot:example.com"
    event.url = "mxc://example.org/image_123"
    mock_matrix_room.room_id = "!room:example.com"

    await matrix_channel._on_room_media_event(mock_matrix_room, event)

    matrix_channel.on_event.assert_not_called()
