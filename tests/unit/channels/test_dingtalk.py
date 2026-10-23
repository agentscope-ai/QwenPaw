# -*- coding: utf-8 -*-
"""Preserved DingTalk delivery/store/media behaviors on the artifact transport.

Host session/ACL/Agent behaviors moved to B147/C2/C3 real worker tests.
The fixture has no old Channel implementation.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations
from concurrent.futures import Future
import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from tests.fixtures.channel_plugins.c6_artifacts import artifact_module
from tests.fixtures.channels.mock_http import MockAiohttpSession
from qwenpaw.exceptions import ChannelError


@pytest.fixture
def dingtalk_channel(temp_media_dir):
    transport = artifact_module("dingtalk", "transport").DingTalkTransport()
    transport.initialize(
        {
            "enabled": True,
            "client_id": "test_client_id",
            "client_secret": "test-only",
            "workspace_dir": str(temp_media_dir.parent),
            "media_dir": str(temp_media_dir),
            "bot_prefix": "[TestBot] ",
        },
    )
    transport._sdk = artifact_module("dingtalk", "sdk")
    transport._state = "running"
    transport._active = True
    return transport


@pytest.fixture
def dingtalk_channel_with_workspace(temp_workspace_dir):
    transport = artifact_module("dingtalk", "transport").DingTalkTransport()
    transport.initialize(
        {
            "enabled": True,
            "client_id": "test_client_id",
            "client_secret": "test-only",
            "workspace_dir": str(temp_workspace_dir),
            "bot_prefix": "[TestBot] ",
        },
    )
    transport._sdk = artifact_module("dingtalk", "sdk")
    transport._state = "running"
    transport._active = True
    return transport


@pytest.fixture
def temp_media_dir(tmp_path) -> Path:
    """Temporary directory for media files."""
    media_dir = tmp_path / ".copaw" / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    return media_dir


@pytest.fixture
def temp_workspace_dir(tmp_path) -> Path:
    """Temporary workspace directory."""
    workspace = tmp_path / ".copaw" / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


@pytest.fixture
def mock_http_session() -> MockAiohttpSession:
    """Create a mock aiohttp session."""
    return MockAiohttpSession()


def _make_oauth_sdk(token: str = "token_123") -> AsyncMock:
    """Return a mock _oauth_sdk whose get_access_token_async returns token."""
    sdk = AsyncMock()
    body = MagicMock()
    body.access_token = token
    response = MagicMock()
    response.body = body
    sdk.get_access_token_async = AsyncMock(return_value=response)
    return sdk


def _make_robot_sdk() -> AsyncMock:
    """Return a mock _robot_sdk with commonly-used async methods."""
    sdk = AsyncMock()
    sdk.org_group_send_with_options_async = AsyncMock(return_value=MagicMock())
    sdk.batch_send_otowith_options_async = AsyncMock(return_value=MagicMock())
    sdk.robot_message_file_download_with_options_async = AsyncMock(
        return_value=MagicMock(),
    )
    return sdk


def _make_card_sdk() -> AsyncMock:
    """Return a mock _card_sdk with commonly-used async methods."""
    sdk = AsyncMock()
    sdk.create_card_with_options_async = AsyncMock(return_value=MagicMock())
    sdk.deliver_card_with_options_async = AsyncMock(return_value=MagicMock())
    sdk.streaming_update_with_options_async = AsyncMock(
        return_value=MagicMock(),
    )
    return sdk


@pytest.mark.asyncio
class TestDingTalkSessionWebhook:
    """
    Tests for session webhook storage and retrieval.

    CHAN-D02: 钉钉 sessionWebhook 过期后定时推送
    - sessionWebhook has an expiry time
    - System should refresh/re-obtain valid sessionWebhook
    - Webhooks should be persisted to disk for cron jobs
    """

    async def test_load_session_webhook_from_memory(self, dingtalk_channel):
        """Loading webhook should first check memory."""
        # Pre-populate memory store
        dingtalk_channel._session_webhook_store["dingtalk:sw:memtest"] = {
            "webhook": "http://memory.webhook",
            "expired_time": 9999999999999,
        }

        result = await dingtalk_channel._load_session_webhook(
            "dingtalk:sw:memtest",
        )

        assert result == "http://memory.webhook"

    async def test_load_session_webhook_from_disk(
        self,
        dingtalk_channel_with_workspace,
        temp_workspace_dir,
    ):
        """Loading webhook should fallback to disk if not in memory."""
        channel = dingtalk_channel_with_workspace

        # Create file manually
        store_path = temp_workspace_dir / "dingtalk_session_webhooks.json"
        data = {
            "dingtalk:sw:diskload": {
                "webhook": "http://disk.webhook",
                "expired_time": 9999999999999,
                "conversation_id": "conv_from_disk",
            },
        }
        with open(store_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        result = await channel._load_session_webhook("dingtalk:sw:diskload")

        assert result == "http://disk.webhook"
        # Should also be loaded into memory
        assert "dingtalk:sw:diskload" in channel._session_webhook_store

    async def test_load_session_webhook_not_found_returns_none(
        self,
        dingtalk_channel,
    ):
        """Loading non-existent webhook should return None."""
        result = await dingtalk_channel._load_session_webhook(
            "dingtalk:sw:nonexistent",
        )

        assert result is None

    async def test_load_session_webhook_empty_key_returns_none(
        self,
        dingtalk_channel,
    ):
        """Loading with empty key should return None."""
        result = await dingtalk_channel._load_session_webhook("")

        assert result is None

    async def test_save_session_webhook_empty_key_skips(
        self,
        dingtalk_channel,
    ):
        """Saving with empty key should be skipped."""
        await dingtalk_channel._save_session_webhook(
            webhook_key="",
            session_webhook="http://test",
        )

        assert "" not in dingtalk_channel._session_webhook_store

    async def test_save_session_webhook_empty_webhook_skips(
        self,
        dingtalk_channel,
    ):
        """Saving with empty webhook should be skipped."""
        await dingtalk_channel._save_session_webhook(
            webhook_key="key",
            session_webhook="",
        )

        assert "key" not in dingtalk_channel._session_webhook_store


@pytest.mark.asyncio
class TestDingTalkTokenCache:
    """
    Tests for access token caching mechanism.

    DingTalk access tokens should be cached and only refreshed when expired.
    Uses asyncio loop time (monotonic) not wall clock time.
    """

    async def test_get_access_token_fetches_when_empty(
        self,
        dingtalk_channel,
    ):
        """Should fetch new token when cache is empty."""
        DINGTALK_TOKEN_TTL_SECONDS = artifact_module(
            "dingtalk",
            "constants",
        ).DINGTALK_TOKEN_TTL_SECONDS

        dingtalk_channel._oauth_sdk = _make_oauth_sdk("new_token_123")

        token = await dingtalk_channel._get_access_token()

        assert token == "new_token_123"
        assert dingtalk_channel._token_value == "new_token_123"
        # Token expires in the future (uses loop time + TTL)
        assert (
            dingtalk_channel._token_expires_at
            > asyncio.get_running_loop().time()
        )
        assert dingtalk_channel._token_expires_at <= (
            asyncio.get_running_loop().time() + DINGTALK_TOKEN_TTL_SECONDS
        )

    async def test_get_access_token_uses_cache_when_valid(
        self,
        dingtalk_channel,
        mock_http_session,
    ):
        """Should use cached token when not expired."""
        dingtalk_channel._http = mock_http_session
        dingtalk_channel._token_value = "cached_token"
        dingtalk_channel._token_expires_at = (
            asyncio.get_running_loop().time() + 3600
        )  # Valid for 1 hour

        token = await dingtalk_channel._get_access_token()

        assert token == "cached_token"
        assert mock_http_session.call_count == 0  # No HTTP call made

    async def test_get_access_token_refreshes_when_expired(
        self,
        dingtalk_channel,
    ):
        """Should fetch new token when cached token is expired."""
        dingtalk_channel._oauth_sdk = _make_oauth_sdk("refreshed_token")
        dingtalk_channel._token_value = "old_token"
        dingtalk_channel._token_expires_at = (
            asyncio.get_running_loop().time() - 100
        )  # Expired

        token = await dingtalk_channel._get_access_token()

        assert token == "refreshed_token"
        assert dingtalk_channel._token_value == "refreshed_token"

    async def test_get_access_token_handles_api_error(
        self,
        dingtalk_channel,
    ):
        """Should handle API error gracefully."""
        sdk = AsyncMock()
        sdk.get_access_token_async = AsyncMock(
            side_effect=Exception("invalid credential"),
        )
        dingtalk_channel._oauth_sdk = sdk

        with pytest.raises(ChannelError, match="get accessToken failed"):
            await dingtalk_channel._get_access_token()

    async def test_get_access_token_thread_safe(
        self,
        dingtalk_channel,
    ):
        """Token fetching should be thread-safe (using asyncio.Lock)."""
        dingtalk_channel._oauth_sdk = _make_oauth_sdk("token_123")

        # Simulate concurrent calls
        tokens = await asyncio.gather(
            dingtalk_channel._get_access_token(),
            dingtalk_channel._get_access_token(),
            dingtalk_channel._get_access_token(),
        )

        # All should get the same token
        assert all(t == "token_123" for t in tokens)


@pytest.mark.asyncio
class TestDingTalkSendMethods:
    """
    Tests for send methods using HTTP mocking.

    Covers:
    - send() method
    - _send_via_session_webhook()
    - _send_via_open_api()
    - _send_payload_via_session_webhook()
    """

    async def test_send_via_session_webhook_success(
        self,
        dingtalk_channel,
        mock_http_session,
    ):
        """Successfully send via session webhook."""
        dingtalk_channel._http = mock_http_session
        mock_http_session.expect_post(
            url="https://oapi.dingtalk.com/robot/send",
            response_status=200,
            response_json={"errcode": 0, "errmsg": "ok"},
        )

        result = await dingtalk_channel._send_via_session_webhook(
            session_webhook=(
                "https://oapi.dingtalk.com/robot/send?session=abc"
            ),
            body="Hello from test",
            bot_prefix="[Bot]",
        )

        assert result is True
        assert mock_http_session.call_count == 1

    async def test_send_via_session_webhook_api_error(
        self,
        dingtalk_channel,
    ):
        """Handle API error response with non-zero errcode."""

        # Mock the response
        class MockResponse:
            status = 200

            async def text(self):
                return '{"errcode": 400001, "errmsg": "invalid session"}'

        class MockClientSession:
            def __init__(self, *_args, **_kwargs):
                pass

            async def __aenter__(self):
                return MockResponse()

            async def __aexit__(self, *args):
                pass

        dingtalk_channel._http = MagicMock()
        dingtalk_channel._http.post = MockClientSession

        result = await dingtalk_channel._send_payload_via_session_webhook(
            session_webhook=(
                "https://oapi.dingtalk.com/robot/send?session=abc"
            ),
            payload={"msgtype": "text", "text": {"content": "Hello"}},
        )

        assert result is False

    async def test_send_via_session_webhook_http_error(
        self,
        dingtalk_channel,
        mock_http_session,
    ):
        """Handle HTTP error response."""
        dingtalk_channel._http = mock_http_session
        mock_http_session.expect_post(
            url="https://oapi.dingtalk.com/robot/send",
            response_status=500,
            response_text="Internal Server Error",
        )

        with pytest.raises(TimeoutError, match="outcome is unknown"):
            await dingtalk_channel._send_via_session_webhook(
                session_webhook=(
                    "https://oapi.dingtalk.com/robot/send?session=abc"
                ),
                body="Hello",
            )
        assert mock_http_session.call_count == 1

    async def test_send_payload_via_session_webhook_success(
        self,
        dingtalk_channel,
        mock_http_session,
    ):
        """Send custom payload via session webhook."""
        dingtalk_channel._http = mock_http_session
        mock_http_session.expect_post(
            url="https://oapi.dingtalk.com/robot/send",
            response_status=200,
            response_json={"errcode": 0, "errmsg": "ok"},
        )

        payload = {
            "msgtype": "markdown",
            "markdown": {"title": "Test", "text": "Hello"},
        }
        result = await dingtalk_channel._send_payload_via_session_webhook(
            session_webhook=(
                "https://oapi.dingtalk.com/robot/send?session=abc"
            ),
            payload=payload,
        )

        assert result is True

    async def test_send_via_open_api_group_success(
        self,
        dingtalk_channel,
    ):
        """Send via Open API for group chat."""
        dingtalk_channel._oauth_sdk = _make_oauth_sdk("token_123")
        dingtalk_channel._robot_sdk = _make_robot_sdk()

        result = await dingtalk_channel._send_via_open_api(
            body="Hello group",
            conversation_id="cid_group_123",
            conversation_type="group",
            sender_staff_id="",
        )

        assert result is True
        sdk = dingtalk_channel._robot_sdk
        sdk.org_group_send_with_options_async.assert_called_once()

    async def test_send_via_open_api_dm_success(
        self,
        dingtalk_channel,
    ):
        """Send via Open API for direct message."""
        dingtalk_channel._oauth_sdk = _make_oauth_sdk("token_123")
        dingtalk_channel._robot_sdk = _make_robot_sdk()

        result = await dingtalk_channel._send_via_open_api(
            body="Hello DM",
            conversation_id="cid_dm_123",
            conversation_type="single",
            sender_staff_id="staff_123",
        )

        assert result is True
        sdk = dingtalk_channel._robot_sdk
        sdk.batch_send_otowith_options_async.assert_called_once()

    async def test_send_via_open_api_dm_no_staff_id_fails(
        self,
        dingtalk_channel,
    ):
        """DM should fail without sender_staff_id."""
        dingtalk_channel._oauth_sdk = _make_oauth_sdk("token_123")
        dingtalk_channel._robot_sdk = _make_robot_sdk()

        result = await dingtalk_channel._send_via_open_api(
            body="Hello DM",
            conversation_id="cid_dm_123",
            conversation_type="single",
            sender_staff_id="",  # Empty staff ID
        )

        assert result is False

    async def test_send_disabled_channel_does_nothing(self, dingtalk_channel):
        """Send should return early when channel is disabled."""
        dingtalk_channel.enabled = False

        result = await dingtalk_channel.send(
            to_handle="user123",
            text="Hello",
            meta={},
        )

        # Should not raise, just return
        assert result is None


@pytest.mark.asyncio
class TestDingTalkOpenAPIFallback:
    """
    Tests for Open API fallback when sessionWebhook is expired.

    CHAN-D02: Cron jobs should still work after webhook expires
    """

    async def test_try_open_api_fallback_with_stored_webhook(
        self,
        dingtalk_channel_with_workspace,
    ):
        """Fallback should use stored webhook entry for metadata."""
        channel = dingtalk_channel_with_workspace
        channel._oauth_sdk = _make_oauth_sdk("token_123")
        channel._robot_sdk = _make_robot_sdk()

        # Store webhook entry
        channel._session_webhook_store["dingtalk:sw:storedkey"] = {
            "webhook": "http://stored.webhook",
            "conversation_id": "stored_conv_id",
            "conversation_type": "group",
            "sender_staff_id": "stored_staff",
        }

        result = await channel._try_open_api_fallback(
            text="Fallback message",
            to_handle="dingtalk:sw:storedkey",
            meta={},
        )

        assert result is True

    async def test_try_open_api_fallback_no_conversation_id(
        self,
        dingtalk_channel,
    ):
        """Fallback should fail without conversation_id."""
        result = await dingtalk_channel._try_open_api_fallback(
            text="Test",
            to_handle="dingtalk:sw:unknown",
            meta={},
        )

        assert result is False

    def test_resolve_open_api_params_from_meta(self, dingtalk_channel):
        """Should extract params from meta with priority."""
        meta = {
            "conversation_id": "meta_conv",
            "conversation_type": "meta_type",
            "sender_staff_id": "meta_staff",
        }
        entry = {
            "conversation_id": "entry_conv",
            "conversation_type": "entry_type",
            "sender_staff_id": "entry_staff",
        }

        result = dingtalk_channel._resolve_open_api_params(meta, entry)

        # Meta takes priority
        assert result["conversation_id"] == "meta_conv"
        assert result["conversation_type"] == "meta_type"
        assert result["sender_staff_id"] == "meta_staff"

    def test_resolve_open_api_params_from_entry(self, dingtalk_channel):
        """Should fallback to entry when meta is empty."""
        meta = {}
        entry = {
            "conversation_id": "entry_conv",
            "conversation_type": "entry_type",
            "sender_staff_id": "entry_staff",
        }

        result = dingtalk_channel._resolve_open_api_params(meta, entry)

        assert result["conversation_id"] == "entry_conv"
        assert result["conversation_type"] == "entry_type"
        assert result["sender_staff_id"] == "entry_staff"


class TestDingTalkPartsToText:
    """Tests for _parts_to_single_text method."""

    def test_parts_to_single_text_with_text(self, dingtalk_channel):
        """Should combine text parts."""
        from qwenpaw.app.channels.base import TextContent, ContentType

        parts = [
            TextContent(type=ContentType.TEXT, text="Hello"),
            TextContent(type=ContentType.TEXT, text="World"),
        ]

        result = dingtalk_channel._parts_to_single_text(parts)

        assert "Hello" in result
        assert "World" in result

    def test_parts_to_single_text_with_prefix(self, dingtalk_channel):
        """Should include bot_prefix."""
        from qwenpaw.app.channels.base import TextContent, ContentType

        parts = [TextContent(type=ContentType.TEXT, text="Message")]

        result = dingtalk_channel._parts_to_single_text(
            parts,
            bot_prefix="[Bot]",
        )

        assert "[Bot]" in result
        assert "Message" in result

    def test_parts_to_single_text_with_refusal(self, dingtalk_channel):
        """Should handle refusal content."""
        from qwenpaw.app.channels.base import RefusalContent, ContentType

        parts = [RefusalContent(type=ContentType.REFUSAL, refusal="I cannot")]

        result = dingtalk_channel._parts_to_single_text(parts)

        assert "I cannot" in result

    def test_parts_to_single_text_with_image(self, dingtalk_channel):
        """Media parts should be skipped (delivered separately)."""
        from qwenpaw.app.channels.base import ImageContent, ContentType

        parts = [
            ImageContent(type=ContentType.IMAGE, image_url="http://img.jpg"),
        ]

        result = dingtalk_channel._parts_to_single_text(parts)

        assert result == ""

    def test_parts_to_single_text_empty_list(self, dingtalk_channel):
        """Should handle empty parts list."""
        result = dingtalk_channel._parts_to_single_text([])

        assert result == ""


class TestDingTalkGetSessionWebhook:
    """Tests for _get_session_webhook method."""

    def test_get_session_webhook_from_meta(self, dingtalk_channel):
        """Should get webhook from meta dict."""
        result = dingtalk_channel._get_session_webhook(
            {"session_webhook": "http://meta.webhook"},
        )

        assert result == "http://meta.webhook"

    def test_get_session_webhook_none_meta(self, dingtalk_channel):
        """Should handle None meta."""
        result = dingtalk_channel._get_session_webhook(None)

        assert result is None

    def test_get_session_webhook_empty_meta(self, dingtalk_channel):
        """Should handle empty meta."""
        result = dingtalk_channel._get_session_webhook({})

        assert result is None


class TestDingTalkUtils:
    """Tests for utility functions in utils.py."""

    def test_guess_suffix_from_file_content_pdf(self, tmp_path):
        """Should detect PDF files by magic bytes."""
        guess_suffix_from_file_content = artifact_module(
            "dingtalk",
            "utils",
        ).guess_suffix_from_file_content

        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 test content")

        result = guess_suffix_from_file_content(pdf_file)

        assert result == ".pdf"

    def test_guess_suffix_from_file_content_png(self, tmp_path):
        """Should detect PNG files by magic bytes."""
        guess_suffix_from_file_content = artifact_module(
            "dingtalk",
            "utils",
        ).guess_suffix_from_file_content

        png_file = tmp_path / "test.png"
        png_file.write_bytes(b"\x89PNG\r\n\x1a\n test content")

        result = guess_suffix_from_file_content(png_file)

        assert result == ".png"

    def test_guess_suffix_from_file_content_jpg(self, tmp_path):
        """Should detect JPG files by magic bytes."""
        guess_suffix_from_file_content = artifact_module(
            "dingtalk",
            "utils",
        ).guess_suffix_from_file_content

        jpg_file = tmp_path / "test.jpg"
        jpg_file.write_bytes(b"\xff\xd8\xff test content")

        result = guess_suffix_from_file_content(jpg_file)

        assert result == ".jpg"

    def test_guess_suffix_from_file_content_unknown(self, tmp_path):
        """Should return None for unknown file types."""
        guess_suffix_from_file_content = artifact_module(
            "dingtalk",
            "utils",
        ).guess_suffix_from_file_content

        unknown_file = tmp_path / "test.unknown"
        unknown_file.write_bytes(
            b"unknown content that doesn't match any magic",
        )

        result = guess_suffix_from_file_content(unknown_file)

        assert result is None

    def test_guess_suffix_from_nonexistent_file(self, tmp_path):
        """Should handle non-existent file."""
        guess_suffix_from_file_content = artifact_module(
            "dingtalk",
            "utils",
        ).guess_suffix_from_file_content

        result = guess_suffix_from_file_content(tmp_path / "nonexistent.bin")

        assert result is None


@pytest.mark.asyncio
class TestDingTalkMediaUpload:
    """Tests for media upload functionality."""

    async def test_upload_media_success(
        self,
        dingtalk_channel,
        mock_http_session,
    ):
        """Successfully upload media file."""
        dingtalk_channel._oauth_sdk = _make_oauth_sdk("token_123")
        dingtalk_channel._http = mock_http_session

        # Upload media via HTTP (oapi endpoint)
        mock_http_session.expect_post(
            url="https://oapi.dingtalk.com/media/upload",
            response_status=200,
            response_json={
                "errcode": 0,
                "media_id": "media_abc123",
            },
        )

        result = await dingtalk_channel._upload_media(
            data=b"file content",
            media_type="image",
            filename="test.jpg",
        )

        assert result == "media_abc123"

    async def test_upload_media_api_error(
        self,
        dingtalk_channel,
        mock_http_session,
    ):
        """Handle media upload API error."""
        dingtalk_channel._oauth_sdk = _make_oauth_sdk("token_123")
        dingtalk_channel._http = mock_http_session

        # Upload call returns error
        mock_http_session.expect_post(
            url="https://oapi.dingtalk.com/media/upload",
            response_status=200,
            response_json={"errcode": 40001, "errmsg": "upload failed"},
        )

        result = await dingtalk_channel._upload_media(
            data=b"file content",
            media_type="image",
            filename="test.jpg",
        )

        assert result is None

    async def test_upload_media_http_error(
        self,
        dingtalk_channel,
        mock_http_session,
    ):
        """Handle media upload HTTP error."""
        dingtalk_channel._oauth_sdk = _make_oauth_sdk("token_123")
        dingtalk_channel._http = mock_http_session

        # Upload call returns HTTP error
        mock_http_session.expect_post(
            url="https://oapi.dingtalk.com/media/upload",
            response_status=500,
            response_text="Internal Server Error",
        )

        result = await dingtalk_channel._upload_media(
            data=b"file content",
            media_type="image",
            filename="test.jpg",
        )

        assert result is None


class TestDingTalkAICardStore:
    """Tests for AICardPendingStore."""

    def test_load_empty_store(self, tmp_path):
        """Loading from non-existent file returns empty list."""
        AICardPendingStore = artifact_module(
            "dingtalk",
            "ai_card",
        ).AICardPendingStore

        store = AICardPendingStore(tmp_path / "nonexistent.json")
        result = store.load()

        assert result == []

    def test_load_existing_cards(self, tmp_path):
        """Loading from existing file returns cards."""
        AICardPendingStore = artifact_module(
            "dingtalk",
            "ai_card",
        ).AICardPendingStore

        card_file = tmp_path / "cards.json"
        card_file.write_text(
            json.dumps(
                {
                    "version": 1,
                    "pending_cards": [
                        {"account_id": "user1", "card_instance_id": "card1"},
                        {"account_id": "user2", "card_instance_id": "card2"},
                    ],
                },
            ),
            encoding="utf-8",
        )

        store = AICardPendingStore(card_file)
        result = store.load()

        assert len(result) == 2
        assert result[0]["account_id"] == "user1"

    def test_save_cards(self, tmp_path):
        """Saving cards writes to file."""
        AICardPendingStore = artifact_module(
            "dingtalk",
            "ai_card",
        ).AICardPendingStore
        ActiveAICard = artifact_module("dingtalk", "ai_card").ActiveAICard

        store = AICardPendingStore(tmp_path / "cards.json")

        cards = {
            "card1": ActiveAICard(
                card_instance_id="card1",
                access_token="token123",
                conversation_id="conv1",
                account_id="user1",
                store_path="/tmp/card1",
                created_at=1234567890,
                last_updated=1234567890,
                state="2",  # INPUTING
            ),
        }

        store.save(cards)

        saved_file = tmp_path / "cards.json"
        assert saved_file.exists()

        data = json.loads(saved_file.read_text(encoding="utf-8"))
        assert data["version"] == 1
        assert len(data["pending_cards"]) == 1
        # access_token should be stripped
        assert "access_token" not in data["pending_cards"][0]

    def test_save_skips_terminal_states(self, tmp_path):
        """Saving should skip cards in terminal states."""
        AICardPendingStore = artifact_module(
            "dingtalk",
            "ai_card",
        ).AICardPendingStore
        ActiveAICard = artifact_module("dingtalk", "ai_card").ActiveAICard
        FINISHED = artifact_module("dingtalk", "ai_card").FINISHED
        FAILED = artifact_module("dingtalk", "ai_card").FAILED

        store = AICardPendingStore(tmp_path / "cards.json")

        cards = {
            "finished_card": ActiveAICard(
                card_instance_id="finished_card",
                access_token="token",
                conversation_id="conv1",
                account_id="user1",
                store_path="/tmp",
                created_at=1234567890,
                last_updated=1234567890,
                state=FINISHED,
            ),
            "failed_card": ActiveAICard(
                card_instance_id="failed_card",
                access_token="token",
                conversation_id="conv2",
                account_id="user2",
                store_path="/tmp",
                created_at=1234567890,
                last_updated=1234567890,
                state=FAILED,
            ),
            "active_card": ActiveAICard(
                card_instance_id="active_card",
                access_token="token",
                conversation_id="conv3",
                account_id="user3",
                store_path="/tmp",
                created_at=1234567890,
                last_updated=1234567890,
                state="2",  # INPUTING
            ),
        }

        store.save(cards)

        data = json.loads(
            (tmp_path / "cards.json").read_text(encoding="utf-8"),
        )
        assert len(data["pending_cards"]) == 1
        assert data["pending_cards"][0]["card_instance_id"] == "active_card"


@pytest.mark.asyncio
class TestDingTalkSendContentParts:
    """
    Tests for send_content_parts method.

    DingTalk-specific behavior for sending various content types.
    """

    async def test_send_content_parts_empty_parts_skipped(
        self,
        dingtalk_channel,
    ):
        """Empty parts list should not send anything."""
        with patch.object(
            dingtalk_channel,
            "send",
            new_callable=AsyncMock,
        ) as mock_send:
            await dingtalk_channel.send_content_parts(
                to_handle="user123",
                parts=[],
                meta={},
            )

            mock_send.assert_not_called()

    async def test_send_content_parts_whitespace_text_skipped(
        self,
        dingtalk_channel,
    ):
        """Whitespace-only text should not send a prefix-only message."""
        from qwenpaw.app.channels.base import TextContent, ContentType

        parts = [TextContent(type=ContentType.TEXT, text="   \n\t")]

        with patch.object(
            dingtalk_channel,
            "send",
            new_callable=AsyncMock,
        ) as mock_send:
            await dingtalk_channel.send_content_parts(
                to_handle="dingtalk:sw:test",
                parts=parts,
                meta={"bot_prefix": "[TestBot] "},
            )

            mock_send.assert_not_called()

    async def test_send_content_parts_text_failure_logs_without_strict_meta(
        self,
        dingtalk_channel,
    ):
        """Conversation replies should not fail the whole agent pipeline."""
        from qwenpaw.app.channels.base import TextContent, ContentType

        parts = [TextContent(type=ContentType.TEXT, text="Hello")]

        with (
            patch.object(
                dingtalk_channel,
                "_send_via_session_webhook",
                new_callable=AsyncMock,
                return_value=False,
            ) as mock_webhook,
            patch.object(
                dingtalk_channel,
                "_try_open_api_fallback",
                new_callable=AsyncMock,
                return_value=False,
            ) as mock_fallback,
        ):
            # Should complete without raising even when both hops fail.
            await dingtalk_channel.send_content_parts(
                to_handle="dingtalk:sw:test",
                parts=parts,
                meta={"session_webhook": "http://webhook.url"},
            )

            # Verify the full webhook -> Open API fallback chain ran.
            mock_webhook.assert_awaited()
            mock_fallback.assert_awaited()

    async def test_send_content_parts_text_failure_raises_for_api_send(
        self,
        dingtalk_channel,
    ):
        """Explicit API delivery failure should surface to callers."""
        from qwenpaw.app.channels.base import TextContent, ContentType

        parts = [TextContent(type=ContentType.TEXT, text="Hello")]

        with (
            patch.object(
                dingtalk_channel,
                "_send_via_session_webhook",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch.object(
                dingtalk_channel,
                "_try_open_api_fallback",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            with pytest.raises(ChannelError, match="Open API fallback"):
                await dingtalk_channel.send_content_parts(
                    to_handle="dingtalk:sw:test",
                    parts=parts,
                    meta={
                        "_api_send": True,
                        "session_webhook": "http://webhook.url",
                    },
                )

    async def test_send_content_parts_with_file(
        self,
        dingtalk_channel,
        mock_http_session,
        tmp_path,
    ):
        """Send with file content uploads file and sends via webhook."""
        dingtalk_channel._http = mock_http_session

        from qwenpaw.app.channels.base import FileContent, ContentType

        # Create a test file
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"%PDF-1.4 test content")

        with patch.object(
            dingtalk_channel,
            "_upload_media",
            return_value="media_file_123",
        ) as mock_upload:
            with patch.object(
                dingtalk_channel,
                "_send_payload_via_session_webhook",
                return_value=True,
            ):
                parts = [
                    FileContent(
                        type=ContentType.FILE,
                        file_url=str(test_file),
                    ),
                ]

                await dingtalk_channel.send_content_parts(
                    to_handle="user123",
                    parts=parts,
                    meta={"session_webhook": "http://webhook.url"},
                )

                mock_upload.assert_called_once()


@pytest.mark.asyncio
class TestDingTalkEdgeCases:
    """Additional edge case tests."""

    async def test_start_disabled_channel(self, dingtalk_channel):
        """Starting disabled channel should succeed without action."""
        dingtalk_channel.enabled = False

        # Should not raise
        await dingtalk_channel.start()

    async def test_stop_disabled_channel(self, dingtalk_channel):
        """Stopping disabled channel should succeed without action."""
        dingtalk_channel.enabled = False

        # Should not raise
        await dingtalk_channel.stop()

    async def test_stop_without_start(self, dingtalk_channel):
        """Stopping without prior start should succeed."""
        # Should not raise
        await dingtalk_channel.stop()


@pytest.mark.asyncio
class TestDingTalkAICardMethods:
    """Tests for AI Card streaming methods."""

    async def test_create_ai_card_success(
        self,
        dingtalk_channel,
    ):
        """Successfully create AI card."""
        # Configure channel for AI card
        dingtalk_channel.message_type = "card"
        dingtalk_channel.card_template_id = "template_123"
        dingtalk_channel.card_template_key = "content"
        dingtalk_channel.robot_code = "robot_123"
        dingtalk_channel.card_auto_layout = True
        dingtalk_channel._oauth_sdk = _make_oauth_sdk("token_123")
        dingtalk_channel._card_sdk = _make_card_sdk()

        card = await dingtalk_channel._create_ai_card(
            conversation_id="cid_test_123",
            meta={"sender_staff_id": "user123", "is_group": True},
        )

        assert card is not None
        assert card.conversation_id == "cid_test_123"
        assert card.card_instance_id.startswith("card_")

    async def test_create_ai_card_group_conversation(
        self,
        dingtalk_channel,
    ):
        """Create AI card for group conversation."""
        dingtalk_channel.message_type = "card"
        dingtalk_channel.card_template_id = "template_123"
        dingtalk_channel.card_template_key = "content"
        dingtalk_channel.robot_code = "robot_123"
        dingtalk_channel._oauth_sdk = _make_oauth_sdk("token_123")
        dingtalk_channel._card_sdk = _make_card_sdk()

        card = await dingtalk_channel._create_ai_card(
            conversation_id="cid_group_123",
            meta={"is_group": True},
        )

        assert card is not None

    async def test_create_ai_card_dm_requires_staff_id(
        self,
        dingtalk_channel,
    ):
        """DM card creation requires sender_staff_id."""
        dingtalk_channel.message_type = "card"
        dingtalk_channel.card_template_id = "template_123"
        dingtalk_channel.card_template_key = "content"
        dingtalk_channel.robot_code = "robot_123"
        dingtalk_channel._oauth_sdk = _make_oauth_sdk("token_123")
        dingtalk_channel._card_sdk = _make_card_sdk()

        with pytest.raises(ChannelError, match="missing sender_staff_id"):
            await dingtalk_channel._create_ai_card(
                conversation_id="cid_single_123",
                meta={"is_group": False},
            )

    async def test_create_ai_card_api_error(
        self,
        dingtalk_channel,
    ):
        """Handle API error when creating card."""
        dingtalk_channel.message_type = "card"
        dingtalk_channel.card_template_id = "template_123"
        dingtalk_channel.robot_code = "robot_123"
        dingtalk_channel._oauth_sdk = _make_oauth_sdk("token_123")
        card_sdk = _make_card_sdk()
        card_sdk.create_card_with_options_async = AsyncMock(
            side_effect=Exception("invalid_template"),
        )
        dingtalk_channel._card_sdk = card_sdk

        with pytest.raises(ChannelError, match="create ai card failed"):
            await dingtalk_channel._create_ai_card(
                conversation_id="cid_test",
                meta={},
            )

    async def test_stream_ai_card_success(
        self,
        dingtalk_channel,
    ):
        """Successfully stream content to AI card."""
        ActiveAICard = artifact_module("dingtalk", "ai_card").ActiveAICard
        PROCESSING = artifact_module("dingtalk", "ai_card").PROCESSING

        dingtalk_channel.message_type = "card"
        dingtalk_channel.card_template_key = "content"
        dingtalk_channel._card_sdk = _make_card_sdk()

        card = ActiveAICard(
            card_instance_id="card_test_123",
            access_token="token_123",
            conversation_id="cid_test",
            account_id="user123",
            store_path="/tmp",
            created_at=int(time.time() * 1000),
            last_updated=0,
            state=PROCESSING,
        )

        result = await dingtalk_channel._stream_ai_card(
            card,
            "Test content",
            finalize=False,
        )

        assert result is True

    async def test_stream_ai_card_finalize(
        self,
        dingtalk_channel,
    ):
        """Finalize AI card streaming."""
        ActiveAICard = artifact_module("dingtalk", "ai_card").ActiveAICard
        PROCESSING = artifact_module("dingtalk", "ai_card").PROCESSING

        dingtalk_channel.message_type = "card"
        dingtalk_channel.card_template_key = "content"
        dingtalk_channel._card_sdk = _make_card_sdk()

        card = ActiveAICard(
            card_instance_id="card_test_123",
            access_token="token_123",
            conversation_id="cid_test",
            account_id="user123",
            store_path="/tmp",
            created_at=int(time.time() * 1000),
            last_updated=0,
            last_streamed_content="Previous content",
            state=PROCESSING,
        )

        result = await dingtalk_channel._stream_ai_card(
            card,
            "Final content",
            finalize=True,
        )

        assert result is True
        assert card.state == "3"  # FINISHED

    async def test_stream_ai_card_duplicate_content_skipped(
        self,
        dingtalk_channel,
        mock_http_session,
    ):
        """Skip streaming if content hasn't changed."""
        ActiveAICard = artifact_module("dingtalk", "ai_card").ActiveAICard
        PROCESSING = artifact_module("dingtalk", "ai_card").PROCESSING

        dingtalk_channel.message_type = "card"
        dingtalk_channel.card_template_key = "content"
        dingtalk_channel._http = mock_http_session

        card = ActiveAICard(
            card_instance_id="card_test_123",
            access_token="token_123",
            conversation_id="cid_test",
            account_id="user123",
            store_path="/tmp",
            created_at=1234567890,
            last_updated=1234567890,
            last_streamed_content="Same content",
            state=PROCESSING,
        )

        # Should return False without making HTTP call
        result = await dingtalk_channel._stream_ai_card(
            card,
            "Same content",
            finalize=False,
        )

        assert result is False

    async def test_stream_ai_card_token_refresh(
        self,
        dingtalk_channel,
    ):
        """Refresh token on 401 response from SDK."""
        from Tea.exceptions import TeaException

        ActiveAICard = artifact_module("dingtalk", "ai_card").ActiveAICard
        PROCESSING = artifact_module("dingtalk", "ai_card").PROCESSING

        dingtalk_channel.message_type = "card"
        dingtalk_channel.card_template_key = "content"
        dingtalk_channel._oauth_sdk = _make_oauth_sdk("new_token_2")

        # First streaming call raises 401, second succeeds
        card_sdk = _make_card_sdk()
        exc_401 = TeaException(
            {"data": {"statusCode": 401}, "message": "Unauthorized"},
        )
        card_sdk.streaming_update_with_options_async = AsyncMock(
            side_effect=[exc_401, None],
        )
        dingtalk_channel._card_sdk = card_sdk

        card = ActiveAICard(
            card_instance_id="card_test_123",
            access_token="old_token",
            conversation_id="cid_test",
            account_id="user123",
            store_path="/tmp",
            created_at=int(time.time() * 1000),
            last_updated=0,
            state=PROCESSING,
        )

        result = await dingtalk_channel._stream_ai_card(
            card,
            "New content",
            finalize=False,
        )

        assert result is True

    async def test_recover_active_cards(
        self,
        dingtalk_channel,
        mock_http_session,
    ):
        """Recover active cards on startup."""
        dingtalk_channel.message_type = "card"
        dingtalk_channel.card_template_id = "template_123"
        dingtalk_channel.robot_code = "robot_123"
        dingtalk_channel._http = mock_http_session

        # Mock stored cards
        dingtalk_channel._card_store.load = MagicMock(
            return_value=[
                {
                    "card_instance_id": "card_old_1",
                    "conversation_id": "cid_old_1",
                    "state": "2",  # PROCESSING
                    "created_at": 1234567890,
                    "last_updated": 1234567890,
                },
            ],
        )

        mock_http_session.expect_post(
            url="https://api.dingtalk.com/v1.0/oauth2/accessToken",
            response_status=200,
            response_json={"accessToken": "token_123", "expireIn": 7200},
        )
        mock_http_session.expect_put(
            url="https://api.dingtalk.com/v1.0/card/streaming",
            response_status=200,
            response_json={"success": True},
        )

        await dingtalk_channel._recover_active_cards()

        # Card should be removed from active cards after recovery + finalize
        assert "cid_old_1" not in dingtalk_channel._active_cards

    async def test_ai_card_disabled_returns_none(self, dingtalk_channel):
        """AI card methods return None when disabled."""
        dingtalk_channel.message_type = "text"  # Not card

        result = await dingtalk_channel._create_ai_card(
            conversation_id="cid_test",
            meta={},
        )

        assert result is None

    def test_build_ai_card_initial_text(self, dingtalk_channel):
        """Build initial text for AI card."""
        dingtalk_channel.bot_prefix = "[Bot] "

        result = dingtalk_channel._build_ai_card_initial_text()

        assert result.startswith("[Bot] ")


@pytest.mark.asyncio
class TestDingTalkFileDownload:
    """Tests for media download methods."""

    async def test_fetch_bytes_from_url_success(
        self,
        dingtalk_channel,
        mock_http_session,
    ):
        """Successfully fetch bytes from URL."""
        dingtalk_channel._http = mock_http_session
        mock_http_session.expect_get(
            url="https://example.com/file.pdf",
            response_status=200,
            response_data=b"PDF content",
        )

        result = await dingtalk_channel._fetch_bytes_from_url(
            "https://example.com/file.pdf",
        )

        assert result == b"PDF content"

    async def test_fetch_bytes_from_url_http_error(
        self,
        dingtalk_channel,
        mock_http_session,
    ):
        """Handle HTTP error when fetching bytes."""
        dingtalk_channel._http = mock_http_session
        mock_http_session.expect_get(
            url="https://example.com/file.pdf",
            response_status=404,
            response_text="Not Found",
        )

        result = await dingtalk_channel._fetch_bytes_from_url(
            "https://example.com/file.pdf",
        )

        assert result is None

    async def test_fetch_bytes_from_url_file_protocol(
        self,
        dingtalk_channel,
        tmp_path,
    ):
        """Fetch bytes from file:// URL."""
        test_file = tmp_path / "test.txt"
        test_file.write_bytes(b"file content")

        result = await dingtalk_channel._fetch_bytes_from_url(
            f"file://{test_file}",
        )

        assert result == b"file content"

    async def test_fetch_bytes_from_url_empty_file(
        self,
        dingtalk_channel,
        tmp_path,
    ):
        """Handle empty file - returns empty bytes not None."""
        test_file = tmp_path / "empty.txt"
        test_file.write_bytes(b"")

        result = await dingtalk_channel._fetch_bytes_from_url(
            f"file://{test_file}",
        )

        # Empty files return empty bytes, not None
        assert result == b""

    async def test_download_media_to_local_success(
        self,
        dingtalk_channel,
        mock_http_session,
        tmp_path,
    ):
        """Successfully download media to local."""
        dingtalk_channel._http = mock_http_session
        dingtalk_channel._media_dir = tmp_path

        mock_http_session.expect_get(
            url="https://download.example.com/file.jpg",
            response_status=200,
            response_data=b"\xff\xd8\xff\xe0\x00\x10JFIF",  # JPEG magic
            headers={"Content-Type": "image/jpeg"},
        )

        result = await dingtalk_channel._download_media_to_local(
            url="https://download.example.com/file.jpg",
            safe_key="test_key_123",
            filename_hint="image.jpg",
        )

        assert result is not None
        assert Path(result).exists()

    async def test_download_media_to_local_with_content_disposition(
        self,
        dingtalk_channel,
        mock_http_session,
        tmp_path,
    ):
        """Extract filename from Content-Disposition header."""
        dingtalk_channel._http = mock_http_session
        dingtalk_channel._media_dir = tmp_path

        mock_http_session.expect_get(
            url="https://download.example.com/file",
            response_status=200,
            response_data=b"content",
            headers={
                "Content-Disposition": 'attachment; filename="document.pdf"',
            },
        )

        result = await dingtalk_channel._download_media_to_local(
            url="https://download.example.com/file",
            safe_key="test_key",
            filename_hint="unknown.bin",
        )

        assert result is not None
        assert result.endswith(".pdf")

    async def test_download_media_to_local_magic_suffix(
        self,
        dingtalk_channel,
        mock_http_session,
        tmp_path,
    ):
        """Detect real suffix from magic bytes for .file extension."""
        dingtalk_channel._http = mock_http_session
        dingtalk_channel._media_dir = tmp_path

        # PNG magic bytes
        mock_http_session.expect_get(
            url="https://download.example.com/image.file",
            response_status=200,
            response_data=b"\x89PNG\r\n\x1a\n" + b"png data",
            headers={"Content-Type": "application/octet-stream"},
        )

        result = await dingtalk_channel._download_media_to_local(
            url="https://download.example.com/image.file",
            safe_key="test_key",
            filename_hint="image.file",
        )

        assert result is not None
        assert result.endswith(".png")

    async def test_download_media_to_local_http_error(
        self,
        dingtalk_channel,
        mock_http_session,
    ):
        """Handle HTTP error when downloading media."""
        dingtalk_channel._http = mock_http_session

        mock_http_session.expect_get(
            url="https://download.example.com/file.jpg",
            response_status=500,
            response_text="Internal Server Error",
        )

        result = await dingtalk_channel._download_media_to_local(
            url="https://download.example.com/file.jpg",
            safe_key="test_key",
            filename_hint="file.jpg",
        )

        assert result is None

    async def test_download_media_to_local_invalid_url(
        self,
        dingtalk_channel,
    ):
        """Handle invalid URL."""
        result = await dingtalk_channel._download_media_to_local(
            url="not-a-url",
            safe_key="test_key",
        )

        assert result is None

    async def test_fetch_and_download_media_success(
        self,
        dingtalk_channel,
        mock_http_session,
        tmp_path,
    ):
        """Successfully fetch and download media."""
        dingtalk_channel._http = mock_http_session
        dingtalk_channel._media_dir = tmp_path
        dingtalk_channel._oauth_sdk = _make_oauth_sdk("token_123")

        # Mock robot SDK download URL response
        robot_sdk = _make_robot_sdk()
        body = MagicMock()
        body.download_url = "https://cdn.example.com/file.pdf"
        sdk_response = MagicMock()
        sdk_response.body = body
        robot_sdk.robot_message_file_download_with_options_async = AsyncMock(
            return_value=sdk_response,
        )
        dingtalk_channel._robot_sdk = robot_sdk

        # Download file via HTTP
        mock_http_session.expect_get(
            url="https://cdn.example.com/file.pdf",
            response_status=200,
            response_data=b"%PDF-1.4 content",
            headers={"Content-Type": "application/pdf"},
        )

        result = await dingtalk_channel._fetch_and_download_media(
            download_code="dl_code_123",
            robot_code="robot_123",
            filename_hint="document.pdf",
        )

        assert result is not None
        assert Path(result).exists()

    async def test_get_message_file_download_url(
        self,
        dingtalk_channel,
    ):
        """Get download URL for message file."""
        dingtalk_channel._oauth_sdk = _make_oauth_sdk("token_123")

        robot_sdk = _make_robot_sdk()
        body = MagicMock()
        body.download_url = "https://cdn.example.com/file.pdf"
        sdk_response = MagicMock()
        sdk_response.body = body
        robot_sdk.robot_message_file_download_with_options_async = AsyncMock(
            return_value=sdk_response,
        )
        dingtalk_channel._robot_sdk = robot_sdk

        result = await dingtalk_channel._get_message_file_download_url(
            download_code="dl_code_123",
            robot_code="robot_123",
        )

        assert result == "https://cdn.example.com/file.pdf"

    async def test_get_message_file_download_url_api_error(
        self,
        dingtalk_channel,
        mock_http_session,
    ):
        """Handle API error when getting download URL."""
        dingtalk_channel._http = mock_http_session

        mock_http_session.expect_post(
            url="https://api.dingtalk.com/v1.0/oauth2/accessToken",
            response_status=200,
            response_json={"accessToken": "token_123", "expireIn": 7200},
        )
        mock_http_session.expect_post(
            url="https://api.dingtalk.com/v1.0/robot/messageFiles/download",
            response_status=200,
            response_json={"errcode": 40001, "errmsg": "invalid code"},
        )

        result = await dingtalk_channel._get_message_file_download_url(
            download_code="invalid_code",
            robot_code="robot_123",
        )

        assert result is None


@pytest.mark.asyncio
class TestDingTalkSendMethodsExtended:
    """Extended tests for send methods."""

    async def test_get_session_webhook_for_send_from_meta(
        self,
        dingtalk_channel,
    ):
        """Get webhook from meta when available."""
        meta = {"session_webhook": "http://meta.webhook"}

        result = await dingtalk_channel._get_session_webhook_for_send(
            to_handle="dingtalk:sw:test",
            meta=meta,
        )

        assert result == "http://meta.webhook"

    async def test_get_session_webhook_for_send_from_store(
        self,
        dingtalk_channel,
    ):
        """Get webhook from store when not in meta."""
        # Pre-populate store
        dingtalk_channel._session_webhook_store["dingtalk:sw:storedkey"] = {
            "webhook": "http://stored.webhook",
            "expired_time": 9999999999999,
        }

        result = await dingtalk_channel._get_session_webhook_for_send(
            to_handle="dingtalk:sw:storedkey",
            meta={},
        )

        assert result == "http://stored.webhook"

    async def test_get_session_webhook_for_send_current_request_no_webhook(
        self,
        dingtalk_channel,
    ):
        """Don't use store if request has no webhook (could be expired)."""
        # Pre-populate store
        dingtalk_channel._session_webhook_store["dingtalk:sw:testkey"] = {
            "webhook": "http://stored.webhook",
            "expired_time": 9999999999999,
        }

        # Current request has conversation_id but no webhook
        result = await dingtalk_channel._get_session_webhook_for_send(
            to_handle="dingtalk:sw:testkey",
            meta={"conversation_id": "cid_test"},
        )

        assert result is None

    async def test_send_with_fallback_to_open_api(
        self,
        dingtalk_channel,
        mock_http_session,
    ):
        """Send with fallback to Open API when webhook fails."""
        dingtalk_channel._http = mock_http_session
        dingtalk_channel._oauth_sdk = _make_oauth_sdk("token_123")
        dingtalk_channel._robot_sdk = _make_robot_sdk()

        # Store webhook entry
        dingtalk_channel._session_webhook_store["dingtalk:sw:test"] = {
            "webhook": "http://expired.webhook",
            "conversation_id": "cid_test",
            "conversation_type": "group",
            "sender_staff_id": "",
        }

        # Webhook call fails
        mock_http_session.expect_post(
            url="http://expired.webhook",
            response_status=400,
            response_json={"errcode": 40014, "errmsg": "invalid session"},
        )

        await dingtalk_channel.send(
            to_handle="dingtalk:sw:test",
            text="Test message",
            meta={},
        )

    async def test_send_no_delivery_target_logs_without_strict_meta(
        self,
        dingtalk_channel,
        mock_http_session,
    ):
        """Conversation replies should not raise on missing target metadata."""
        dingtalk_channel._http = mock_http_session

        with patch(
            "c6_artifact_dingtalk.transport.logger.warning",
        ) as mock_warning:
            # Should return quietly (no raise) for non-API sends.
            await dingtalk_channel.send(
                to_handle="unknown_handle",
                text="Test message",
                meta={},
            )

        assert any(
            "no sessionWebhook" in str(call)
            for call in mock_warning.call_args_list
        )

    async def test_send_no_delivery_target_raises_for_api_send(
        self,
        dingtalk_channel,
        mock_http_session,
    ):
        """Explicit send should fail when no DingTalk target is reachable."""
        dingtalk_channel._http = mock_http_session

        with pytest.raises(ChannelError, match="no sessionWebhook"):
            await dingtalk_channel.send(
                to_handle="unknown_handle",
                text="Test message",
                meta={"_api_send": True},
            )

    async def test_send_open_api_fallback_failure_raises_for_api_send(
        self,
        dingtalk_channel,
        mock_http_session,
    ):
        """Open API transport failure should fail explicit sends."""
        dingtalk_channel._http = mock_http_session

        with patch.object(
            dingtalk_channel,
            "_send_robot_message",
            new_callable=AsyncMock,
            return_value=False,
        ):
            with pytest.raises(ChannelError, match="Open API send failed"):
                await dingtalk_channel.send(
                    to_handle="unknown_handle",
                    text="Test message",
                    meta={
                        "_api_send": True,
                        "conversation_id": "cid_test",
                    },
                )


@pytest.mark.asyncio
class TestDingTalkMediaPartSending:
    """Tests for sending media parts via webhook."""

    async def test_send_media_part_via_webhook_with_media_id(
        self,
        dingtalk_channel,
        mock_http_session,
    ):
        """Send media part that already has media_id."""
        dingtalk_channel._http = mock_http_session

        mock_http_session.expect_post(
            url="https://oapi.dingtalk.com/robot/send",
            response_status=200,
            response_json={"errcode": 0, "errmsg": "ok"},
        )

        from qwenpaw.app.channels.base import ImageContent, ContentType

        part = ImageContent(
            type=ContentType.IMAGE,
            image_url="http://example.com/img.jpg",
            media_id="existing_media_123",
        )

        result = await dingtalk_channel._send_media_part_via_webhook(
            session_webhook=(
                "https://oapi.dingtalk.com/robot/send?session=abc"
            ),
            part=part,
        )

        assert result is True

    async def test_send_media_part_via_webhook_fetch_and_upload(
        self,
        dingtalk_channel,
        mock_http_session,
        tmp_path,
    ):
        """Fetch and upload when no media_id."""
        dingtalk_channel._http = mock_http_session
        dingtalk_channel._media_dir = tmp_path

        # Mock file download
        mock_http_session.expect_get(
            url="http://example.com/img.jpg",
            response_status=200,
            response_data=b"\xff\xd8\xff\xe0image data",
        )

        # Mock token and upload
        mock_http_session.expect_post(
            url="https://api.dingtalk.com/v1.0/oauth2/accessToken",
            response_status=200,
            response_json={"accessToken": "token_123", "expireIn": 7200},
        )
        mock_http_session.expect_post(
            url="https://oapi.dingtalk.com/media/upload",
            response_status=200,
            response_json={"media_id": "uploaded_media_123"},
        )

        # Mock send
        mock_http_session.expect_post(
            url="https://oapi.dingtalk.com/robot/send",
            response_status=200,
            response_json={"errcode": 0, "errmsg": "ok"},
        )

        from qwenpaw.app.channels.base import ImageContent, ContentType

        part = ImageContent(
            type=ContentType.IMAGE,
            image_url="http://example.com/img.jpg",
            # No media_id, should fetch and upload
        )

        result = await dingtalk_channel._send_media_part_via_webhook(
            session_webhook=(
                "https://oapi.dingtalk.com/robot/send?session=abc"
            ),
            part=part,
        )

        assert result is True

    async def test_public_image_url_does_not_require_media_id(
        self,
        dingtalk_channel,
        mock_http_session,
    ):
        """Skip sending if media_id is empty after stripping."""
        from qwenpaw.app.channels.base import ImageContent, ContentType

        part = ImageContent(
            type=ContentType.IMAGE,
            image_url="http://example.com/img.jpg",
            media_id="   ",  # Whitespace only
        )

        dingtalk_channel._http = mock_http_session
        mock_http_session.expect_post(response_json={"errcode": 0})
        result = await dingtalk_channel._send_media_part_via_webhook(
            session_webhook=(
                "https://oapi.dingtalk.com/robot/send?session=abc"
            ),
            part=part,
        )

        assert result is True
        assert mock_http_session.call_count == 1

    def test_map_upload_type(self, dingtalk_channel):
        """Map content types to DingTalk upload types."""
        from qwenpaw.app.channels.base import ContentType

        # Create mock parts for each type
        text_part = MagicMock()
        text_part.type = ContentType.TEXT
        assert dingtalk_channel._map_upload_type(text_part) is None

        image_part = MagicMock()
        image_part.type = ContentType.IMAGE
        assert dingtalk_channel._map_upload_type(image_part) == "image"

        audio_part = MagicMock()
        audio_part.type = ContentType.AUDIO
        assert dingtalk_channel._map_upload_type(audio_part) == "voice"

        video_part = MagicMock()
        video_part.type = ContentType.VIDEO
        assert dingtalk_channel._map_upload_type(video_part) == "video"

        file_part = MagicMock()
        file_part.type = ContentType.FILE
        assert dingtalk_channel._map_upload_type(file_part) == "file"

        # Unknown type defaults to file
        unknown_part = MagicMock()
        unknown_part.type = "unknown"
        assert dingtalk_channel._map_upload_type(unknown_part) == "file"

    async def test_send_media_part_video_with_pic_media_id(
        self,
        dingtalk_channel,
        mock_http_session,
    ):
        """Send video with pic_media_id for cover image."""
        dingtalk_channel._http = mock_http_session
        dingtalk_channel._oauth_sdk = _make_oauth_sdk("token_123")

        # Mock the video download
        mock_http_session.expect_get(
            url="http://example.com/video.mp4",
            response_status=200,
            response_data=b"fake video content",
        )
        # Mock media upload endpoint (oapi uses HTTP not SDK)
        mock_http_session.expect_post(
            url="https://oapi.dingtalk.com/media/upload",
            response_status=200,
            response_json={"media_id": "uploaded_media_123"},
        )
        # Mock robot send endpoint
        mock_http_session.expect_post(
            url="https://oapi.dingtalk.com/robot/send",
            response_status=200,
            response_json={"errcode": 0, "errmsg": "ok"},
        )

        from qwenpaw.app.channels.base import VideoContent, ContentType

        part = VideoContent(
            type=ContentType.VIDEO,
            video_url="http://example.com/video.mp4",
            media_id="video_media_123",
            pic_media_id="cover_media_456",
            duration=30,
        )

        result = await dingtalk_channel._send_media_part_via_webhook(
            session_webhook=(
                "https://oapi.dingtalk.com/robot/send?session=abc"
            ),
            part=part,
        )

        assert result is True


@pytest.mark.asyncio
class TestDingTalkLoadSessionWebhookEntry:
    """Tests for _load_session_webhook_entry method."""

    async def test_load_session_webhook_entry_from_memory(
        self,
        dingtalk_channel,
    ):
        """Load full entry from memory."""
        dingtalk_channel._session_webhook_store["dingtalk:sw:fulltest"] = {
            "webhook": "http://full.webhook",
            "expired_time": 9999999999999,
            "conversation_id": "cid_full",
            "conversation_type": "group",
            "sender_staff_id": "staff_full",
        }

        result = await dingtalk_channel._load_session_webhook_entry(
            "dingtalk:sw:fulltest",
        )

        assert result is not None
        assert result["webhook"] == "http://full.webhook"
        assert result["conversation_id"] == "cid_full"

    async def test_load_session_webhook_entry_not_found(
        self,
        dingtalk_channel,
    ):
        """Non-existent entry returns None."""
        result = await dingtalk_channel._load_session_webhook_entry(
            "dingtalk:sw:nonexistent",
        )

        assert result is None


@pytest.mark.asyncio
class TestDingTalkHealthCheck:
    """Tests for DingTalk connection health reporting."""

    @staticmethod
    def _set_runtime_state(
        channel,
        *,
        thread_alive: bool = True,
        websocket_state: str = "OPEN",
        stream_loop_running: bool = True,
    ):
        loop = asyncio.get_running_loop()
        websocket = MagicMock()
        websocket.state.name = websocket_state
        websocket.ping = AsyncMock()
        pong_waiter = loop.create_future()
        pong_waiter.set_result(0.01)
        websocket.ping.return_value = pong_waiter
        client = MagicMock()
        client.websocket = websocket
        client.connection_error = None
        channel._client = client
        channel._stream_thread = MagicMock()
        channel._stream_thread.is_alive.return_value = thread_alive
        if stream_loop_running:
            channel._stream_event_loop = loop
        else:
            channel._stream_event_loop = MagicMock()
            channel._stream_event_loop.is_running.return_value = False
        channel._http = MagicMock()
        channel._http.closed = False
        return websocket

    async def test_reports_healthy_for_live_stream(
        self,
        dingtalk_channel,
    ):
        """A connected and responsive stream should be healthy."""
        websocket = self._set_runtime_state(dingtalk_channel)

        result = await dingtalk_channel.health_check()

        assert result["status"] == "healthy"
        websocket.ping.assert_awaited_once_with()

    @pytest.mark.parametrize(
        (
            "thread_alive",
            "websocket_state",
            "stream_loop_running",
            "expected_detail",
        ),
        [
            (False, "OPEN", True, "Stream thread is not running"),
            (True, "CLOSED", True, "WebSocket connection is not open"),
            (True, "OPEN", False, "Stream event loop is not running"),
        ],
    )
    async def test_reports_unhealthy_for_broken_stream_state(
        self,
        dingtalk_channel,
        thread_alive,
        websocket_state,
        stream_loop_running,
        expected_detail,
    ):
        """Broken stream states should not be reported as healthy."""
        self._set_runtime_state(
            dingtalk_channel,
            thread_alive=thread_alive,
            websocket_state=websocket_state,
            stream_loop_running=stream_loop_running,
        )

        result = await dingtalk_channel.health_check()

        assert result["status"] == "unhealthy"
        assert expected_detail in result["detail"]

    async def test_reports_unhealthy_when_pong_times_out(
        self,
        dingtalk_channel,
    ):
        """An open socket without a Pong response should be unhealthy."""
        websocket = self._set_runtime_state(dingtalk_channel)
        websocket.ping.return_value = (
            asyncio.get_running_loop().create_future()
        )

        with patch(
            "c6_artifact_dingtalk.platform."
            "_STREAM_HEALTH_PING_TIMEOUT_SECONDS",
            0.01,
        ):
            result = await dingtalk_channel.health_check()

        assert result["status"] == "unhealthy"
        assert "WebSocket Ping timed out" in result["detail"]

    async def test_reports_unhealthy_when_ping_fails(
        self,
        dingtalk_channel,
    ):
        """A Ping transport error should be reported as unhealthy."""
        websocket = self._set_runtime_state(dingtalk_channel)
        websocket.ping.side_effect = ConnectionError("socket closed")

        result = await dingtalk_channel.health_check()

        assert result["status"] == "unhealthy"
        assert "WebSocket Ping failed: ConnectionError" in result["detail"]

    async def test_reports_unhealthy_when_ping_is_cancelled(
        self,
        dingtalk_channel,
    ):
        """A Ping cancelled by Stream reconnect should be unhealthy."""
        self._set_runtime_state(dingtalk_channel)

        def cancel_probe(coro, _loop):
            coro.close()
            future = Future()
            future.cancel()
            return future

        with patch(
            "asyncio.run_coroutine_threadsafe",
            side_effect=cancel_probe,
        ):
            result = await dingtalk_channel.health_check()

        assert result["status"] == "unhealthy"
        assert "WebSocket Ping was cancelled" in result["detail"]

    async def test_reports_unhealthy_when_stream_loop_is_blocked(
        self,
        dingtalk_channel,
    ):
        """Health should time out if the Stream loop cannot run Ping."""
        self._set_runtime_state(dingtalk_channel)

        def leave_probe_pending(coro, _loop):
            coro.close()
            return Future()

        with patch(
            "asyncio.run_coroutine_threadsafe",
            side_effect=leave_probe_pending,
        ), patch(
            "c6_artifact_dingtalk.platform."
            "_STREAM_HEALTH_PING_TIMEOUT_SECONDS",
            0.01,
        ):
            result = await dingtalk_channel.health_check()

        assert result["status"] == "unhealthy"
        assert "WebSocket Ping timed out" in result["detail"]
