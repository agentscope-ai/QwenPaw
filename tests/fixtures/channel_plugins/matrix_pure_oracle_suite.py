"""Mechanically retained legacy pure/cache oracles against private MatrixPlatform.

Only the import location and real constructor fixture change. No BaseChannel
shim: these methods still belong to the native platform. E2EE flag tests are
preflight branch checks only, not native olm interoperability evidence.
"""
import asyncio
from pathlib import Path
import sys
from unittest.mock import AsyncMock, MagicMock, Mock, patch
import pytest
from nio import MatrixRoom, RoomMessageText

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "plugins/channel/matrix"))
from qwenpaw_channel_matrix.platform import MatrixPlatform

@pytest.fixture
def matrix_channel(tmp_path):
    return MatrixPlatform({"homeserver": "https://matrix.example.com",
                           "user_id": "@bot:example.com", "access_token": "test_token_123",
                           "workspace_dir": str(tmp_path)}, AsyncMock(), AsyncMock())

@pytest.fixture
def mock_matrix_room():
    room = MagicMock(spec=MatrixRoom)
    room.room_id = "!test_room:example.com"
    room.users = {"@user1:example.com": None, "@user2:example.com": None}
    return room

def test_preflight_keeps_encryption_when_nio_has_backend(matrix_channel):
    """E2EE stays enabled when matrix-nio reports a crypto backend.

    Guards #6476: the preflight checks ``nio.crypto.ENCRYPTION_ENABLED``
    (the flag ``AsyncClientConfig`` validates against) rather than
    probing module names, so it tracks matrix-nio's version-dependent
    backend detection.
    """
    matrix_channel.encryption = True
    with patch(
        "qwenpaw_channel_matrix.platform.ENCRYPTION_ENABLED",
        True,
    ):
        matrix_channel._preflight_e2ee_dependencies()
    assert matrix_channel.encryption is True


def test_preflight_disables_encryption_when_no_nio_backend(
    matrix_channel,
):
    """No matrix-nio crypto backend -> E2EE disabled with a clear error."""
    matrix_channel.encryption = True
    with patch(
        "qwenpaw_channel_matrix.platform.ENCRYPTION_ENABLED",
        False,
    ):
        matrix_channel._preflight_e2ee_dependencies()
    assert matrix_channel.encryption is False


def test_room_history_evicts_least_recent_room(
    matrix_channel,
    monkeypatch,
):
    from qwenpaw_channel_matrix import platform as matrix_module
    from qwenpaw_channel_matrix.platform import HistoryEntry

    monkeypatch.setattr(matrix_module, "ROOM_HISTORY_MAX_ROOMS", 2)
    for room_id in ("!one", "!two", "!three"):
        matrix_channel._record_history(
            room_id,
            HistoryEntry(sender="user", body=room_id),
        )

    assert list(matrix_channel._room_histories) == ["!two", "!three"]


def test_dm_cache_prunes_expired_and_oldest_entries(
    matrix_channel,
    monkeypatch,
):
    from qwenpaw_channel_matrix import platform as matrix_module

    monkeypatch.setattr(matrix_module, "DM_ROOM_CACHE_MAX_ENTRIES", 2)
    matrix_channel._dm_room_cache.update(
        {
            "!old": {"members": [], "ts": 0},
            "!two": {"members": [], "ts": 30_001},
            "!three": {"members": [], "ts": 30_001},
        },
    )

    matrix_channel._prune_dm_room_cache(
        30_001,
    )

    assert list(matrix_channel._dm_room_cache) == ["!two", "!three"]


def test_verification_state_expires_and_cancel_clears_peer(
    matrix_channel,
    monkeypatch,
):
    from qwenpaw_channel_matrix import platform as matrix_module

    monkeypatch.setattr(matrix_module, "VERIFICATION_STATE_MAX_ENTRIES", 1)
    matrix_channel._remember_verification_peer("old", "@old", "D1")
    matrix_channel._remember_verification_peer("new", "@new", "D2")
    matrix_channel._clear_verification_transaction("new")

    assert "old" not in matrix_channel._verification_tx_peers
    assert "new" not in matrix_channel._verification_tx_peers


@pytest.mark.asyncio
async def test_failed_done_keeps_peer_for_retry(matrix_channel):
    matrix_channel._remember_verification_peer("tx", "@user:hs", "D1")
    client = MagicMock()
    client.to_device = AsyncMock(side_effect=RuntimeError("network down"))
    matrix_channel._client = client

    event = MagicMock()
    event.sender = "@user:hs"
    event.source = {"content": {"transaction_id": "tx"}}

    await matrix_channel._handle_unknown_key_verification_done(event)

    assert "tx" in matrix_channel._verification_tx_peers
    assert "tx" not in matrix_channel._sent_verification_done


def test_mxc_to_http_with_valid_mxc(matrix_channel):
    """Test converting valid MXC URL to HTTP."""
    mxc_url = "mxc://matrix.org/media_123"
    http_url = matrix_channel._mxc_to_http(mxc_url)

    expected = (
        "https://matrix.example.com/_matrix/media/v3/download/"
        "matrix.org/media_123"
    )
    assert http_url == expected


def test_mxc_to_http_with_http_url(matrix_channel):
    """Test that HTTP URLs are returned as-is."""
    http_url = "https://example.com/image.png"
    result = matrix_channel._mxc_to_http(http_url)

    assert result == http_url


def test_mxc_to_http_with_invalid_mxc_format(matrix_channel):
    """Test handling of invalid MXC URL format."""
    invalid_mxc = "mxc://noseparator"
    result = matrix_channel._mxc_to_http(invalid_mxc)

    assert result == invalid_mxc


def test_mxc_to_http_with_empty_string(matrix_channel):
    """Test handling of empty string."""
    result = matrix_channel._mxc_to_http("")

    assert result == ""


def test_dm_not_disabled(matrix_channel):
    """Test that DMs pass when not disabled."""
    matrix_channel.dm_disabled = False

    result = matrix_channel._is_channel_disabled(
        "@any_user:example.com",
        "!room:example.com",
        is_dm=True,
    )
    assert result is False


def test_dm_disabled(matrix_channel):
    """Test that DMs are blocked when dm_disabled=True."""
    matrix_channel.dm_disabled = True

    result = matrix_channel._is_channel_disabled(
        "@any_user:example.com",
        "!room:example.com",
        is_dm=True,
    )
    assert result is True


def test_group_not_disabled(matrix_channel):
    """Test that group messages pass when not disabled."""
    matrix_channel.group_disabled = False

    result = matrix_channel._is_channel_disabled(
        "@any_user:example.com",
        "!room:example.com",
        is_dm=False,
    )
    assert result is False


def test_group_disabled(matrix_channel):
    """Test that group messages are blocked when group_disabled=True."""
    matrix_channel.group_disabled = True

    result = matrix_channel._is_channel_disabled(
        "@any_user:example.com",
        "!room:example.com",
        is_dm=False,
    )
    assert result is True


def test_dm_disabled_does_not_affect_group(matrix_channel):
    """Test dm_disabled doesn't block group messages."""
    matrix_channel.dm_disabled = True
    matrix_channel.group_disabled = False

    result = matrix_channel._is_channel_disabled(
        "@any_user:example.com",
        "!room:example.com",
        is_dm=False,
    )
    assert result is False


@pytest.mark.asyncio
async def test_message_callback_detects_mention(
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


@pytest.mark.asyncio
async def test_message_callback_detects_localpart_mention(
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
