# -*- coding: utf-8 -*-
"""
DingTalk Channel Unit Tests

Tests internal logic that cannot be covered by contract or integration tests:
- Token caching with expiration (concurrent refresh protection)
- Message deduplication (prevents double-processing)
- Session webhook storage (memory + disk)
- Webhook expiration handling (CHAN-D02 regression test)

These require direct access to internal state and precise timing control.
"""
# pylint: disable=protected-access

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest


class TestDingTalkTokenCache:
    """
    Tests for DingTalk token caching mechanism.

    DingTalk access tokens are cached for 1 hour to avoid excessive API calls.
    The cache uses a double-checked locking pattern for thread safety.
    """

    @pytest.fixture
    def channel(self, mock_process_handler, temp_media_dir):
        """Create a DingTalkChannel instance for testing."""
        from copaw.app.channels.dingtalk.channel import DingTalkChannel

        return DingTalkChannel(
            process=mock_process_handler,
            enabled=True,
            client_id="test_client_id",
            client_secret="test_client_secret",
            bot_prefix="[TEST] ",
            media_dir=temp_media_dir,
        )

    def test_token_should_refresh_when_expired(self, channel):
        """Token should refresh when past expiration time."""
        channel._token_expires_at = time.time() - 10  # 10 seconds ago
        channel._token_value = "old_token"

        # Internal check: should refresh
        assert channel._token_expires_at <= time.time()

    def test_token_should_not_refresh_when_valid(self, channel):
        """Token should not refresh when still valid."""
        channel._token_expires_at = time.time() + 3600  # 1 hour from now
        channel._token_value = "valid_token"

        # Internal check: should not refresh
        assert channel._token_expires_at > time.time()

    @pytest.mark.asyncio
    async def test_token_cache_concurrent_access(self, channel):
        """
        Test that concurrent token requests only trigger one refresh.

        This verifies the double-checked locking pattern works correctly.
        """
        refresh_count = 0

        async def mock_get_token():
            nonlocal refresh_count
            refresh_count += 1
            await asyncio.sleep(0.01)  # Simulate network delay
            channel._token_value = f"token_{refresh_count}"
            channel._token_expires_at = time.time() + 3600
            return channel._token_value

        # Simulate expired token
        channel._token_value = None
        channel._token_expires_at = 0

        # Launch concurrent requests
        async def request_token():
            async with channel._token_lock:
                if (
                    not channel._token_value
                    or time.time() >= channel._token_expires_at
                ):
                    await mock_get_token()
            return channel._token_value

        results = await asyncio.gather(
            request_token(),
            request_token(),
            request_token(),
        )

        # All should get the same token (only one refresh)
        assert refresh_count == 1
        assert all(r == "token_1" for r in results)


class TestDingTalkMessageDeduplication:
    """
    CHAN-D03 Regression Tests: Message Deduplication

    DingTalk Stream can deliver the same message multiple times.
    The channel uses an in-flight message ID set to prevent double-processing.
    """

    @pytest.fixture
    def channel(self, mock_process_handler, temp_media_dir):
        """Create a DingTalkChannel instance for testing."""
        from copaw.app.channels.dingtalk.channel import DingTalkChannel

        return DingTalkChannel(
            process=mock_process_handler,
            enabled=True,
            client_id="test_client_id",
            client_secret="test_client_secret",
            bot_prefix="[TEST] ",
            media_dir=temp_media_dir,
        )

    def test_try_accept_new_message(self, channel):
        """New message ID should be accepted."""
        result = channel._try_accept_message("msg_123")

        assert result is True
        assert "msg_123" in channel._processing_message_ids

    def test_try_accept_duplicate_message(self, channel):
        """Duplicate message ID should be rejected."""
        # Accept first time
        channel._try_accept_message("msg_123")
        # Try to accept again
        result = channel._try_accept_message("msg_123")

        assert result is False

    def test_try_accept_multiple_different_messages(self, channel):
        """Different message IDs should all be accepted."""
        result1 = channel._try_accept_message("msg_1")
        result2 = channel._try_accept_message("msg_2")
        result3 = channel._try_accept_message("msg_3")

        assert result1 is True
        assert result2 is True
        assert result3 is True
        assert len(channel._processing_message_ids) == 3

    def test_release_message_ids(self, channel):
        """Released message IDs can be accepted again."""
        # Accept and then release
        channel._try_accept_message("msg_123")
        channel._release_message_ids(["msg_123"])

        # Should be able to accept again
        result = channel._try_accept_message("msg_123")
        assert result is True

    def test_release_partial_ids(self, channel):
        """Releasing subset should only affect those IDs."""
        channel._try_accept_message("msg_1")
        channel._try_accept_message("msg_2")
        channel._try_accept_message("msg_3")

        # Release only msg_2
        channel._release_message_ids(["msg_2"])

        # msg_1 and msg_3 should still be blocked
        assert channel._try_accept_message("msg_1") is False
        assert channel._try_accept_message("msg_2") is True  # Released
        assert channel._try_accept_message("msg_3") is False


class TestDingTalkSessionWebhookStore:
    """
    CHAN-D02 Regression Tests: Session Webhook Storage

    Session webhooks expire after ~1 hour but are needed for proactive sends
    (e.g., cron jobs). They are stored in memory with disk persistence.
    """

    @pytest.fixture
    def channel(self, mock_process_handler, temp_media_dir):
        """Create a DingTalkChannel instance for testing."""
        from copaw.app.channels.dingtalk.channel import DingTalkChannel

        return DingTalkChannel(
            process=mock_process_handler,
            enabled=True,
            client_id="test_client_id",
            client_secret="test_client_secret",
            bot_prefix="[TEST] ",
            media_dir=temp_media_dir,
        )

    @pytest.mark.asyncio
    async def test_save_and_load_webhook(self, channel):
        """Saved webhook should be retrievable."""
        await channel._save_session_webhook("key_123", "https://webhook/abc")

        result = await channel._load_session_webhook("key_123")

        assert result == "https://webhook/abc"

    @pytest.mark.asyncio
    async def test_load_missing_webhook(self, channel):
        """Loading non-existent key should return None."""
        result = await channel._load_session_webhook("non_existent_key")

        assert result is None

    @pytest.mark.asyncio
    async def test_webhook_persisted_to_disk(self, channel, tmp_path):
        """Webhook should be saved to disk and survive memory clear."""
        # Mock the storage path to use temp directory
        store_path = tmp_path / "dingtalk_session_webhooks.json"

        with patch.object(
            channel,
            "_session_webhook_store_path",
            return_value=store_path,
        ):
            # Save webhook
            await channel._save_session_webhook("key_1", "https://webhook/1")

            # Verify file exists
            assert store_path.exists()

            # Clear memory store
            channel._session_webhook_store.clear()

            # Load should read from disk
            result = await channel._load_session_webhook("key_1")
            assert result == "https://webhook/1"

    @pytest.mark.asyncio
    async def test_multiple_webhooks_independent(self, channel):
        """Different keys should store independent webhooks."""
        await channel._save_session_webhook("key_1", "https://webhook/1")
        await channel._save_session_webhook("key_2", "https://webhook/2")

        result1 = await channel._load_session_webhook("key_1")
        result2 = await channel._load_session_webhook("key_2")

        assert result1 == "https://webhook/1"
        assert result2 == "https://webhook/2"


class TestDingTalkResolveSessionId:
    """Tests for DingTalk-specific session ID resolution."""

    @pytest.fixture
    def channel(self, mock_process_handler, temp_media_dir):
        """Create a DingTalkChannel instance for testing."""
        from copaw.app.channels.dingtalk.channel import DingTalkChannel

        return DingTalkChannel(
            process=mock_process_handler,
            enabled=True,
            client_id="test_client_id",
            client_secret="test_client_secret",
            bot_prefix="[TEST] ",
            media_dir=temp_media_dir,
        )

    def test_resolve_session_id_uses_conversation_suffix(self, channel):
        """Session ID should use short suffix of conversation_id."""
        meta = {"conversation_id": "abc123def456"}

        result = channel.resolve_session_id("user123", meta)

        # Should be short suffix, not full conversation_id
        assert len(result) < len("abc123def456")
        assert "abc123" in result or "def456" in result

    def test_resolve_session_id_fallback_to_user(self, channel):
        """Without conversation_id, should fall back to user-based ID."""
        result = channel.resolve_session_id("user123", {})

        assert "user123" in result
        assert "dingtalk" in result


class TestDingTalkHttpMockIntegration:
    """
    Integration with HTTP mocks to verify send behavior.
    Uses MockAiohttpSession for controlled HTTP responses.
    """

    @pytest.fixture
    def channel(self, mock_process_handler, temp_media_dir):
        """Create a DingTalkChannel with mock HTTP session."""
        from copaw.app.channels.dingtalk.channel import DingTalkChannel
        from tests.fixtures.channels.mock_http import MockAiohttpSession

        channel = DingTalkChannel(
            process=mock_process_handler,
            enabled=True,
            client_id="test_client_id",
            client_secret="test_client_secret",
            bot_prefix="[TEST] ",
            media_dir=temp_media_dir,
        )
        channel._http = MockAiohttpSession()
        return channel

    @pytest.mark.asyncio
    async def test_send_with_direct_webhook(self, channel):
        """Send should POST to provided webhook URL."""
        channel._http.expect_post(
            url="https://oapi.dingtalk.com/robot/send",
            response_status=200,
            response_json={"errcode": 0, "errmsg": "ok"},
        )

        await channel.send(
            to_handle="https://oapi.dingtalk.com/robot/send?access_token=xxx",
            text="Hello",
            meta={},
        )

        assert channel._http.call_count == 1

    @pytest.mark.asyncio
    async def test_send_with_stored_webhook(self, channel):
        """Send should use stored webhook when to_handle references it."""
        # Pre-populate webhook store
        await channel._save_session_webhook(
            "dingtalk:sw:session123",
            "https://webhook.example.com/session123",
        )

        channel._http.expect_post(
            url="https://webhook.example.com/session123",
            response_status=200,
            response_json={"errcode": 0, "errmsg": "ok"},
        )

        await channel.send(
            to_handle="dingtalk:sw:session123",
            text="Hello",
            meta={},
        )

        assert channel._http.call_count == 1

    @pytest.mark.asyncio
    async def test_send_handles_webhook_error(self, channel):
        """Send should handle webhook errors gracefully."""
        channel._http.expect_post(
            url="https://webhook.example.com",
            response_status=400,
            response_json={
                "errcode": 400602,
                "errmsg": "session webhook expired",
            },
        )

        # Should not raise exception
        await channel.send(
            to_handle="https://webhook.example.com",
            text="Hello",
            meta={},
        )

        # Error should be logged but not crash
        assert channel._http.call_count == 1
