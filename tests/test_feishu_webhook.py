# -*- coding: utf-8 -*-
"""Tests for Feishu webhook functionality."""
# pylint: disable=redefined-outer-name,protected-access
# redefined-outer-name: pytest fixtures are reused across tests
# protected-access: tests need to access internal methods

import base64
import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient

from copaw.app.routers.feishu_webhook import (
    decrypt_body,
    router,
    verify_signature,
)


@pytest.fixture
def app():
    """Create test FastAPI app with webhook router."""
    test_app = FastAPI()
    test_app.include_router(router)

    # Mock app.state
    test_app.state.channel_manager = MagicMock()

    return test_app


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def mock_config():
    """Mock FeishuConfig for testing."""
    config = MagicMock()
    feishu_config = config.channels.feishu
    feishu_config.webhook_enabled = True
    feishu_config.webhook_verification_token = "test_token"
    feishu_config.verification_token = ""
    feishu_config.webhook_encrypt_key = ""
    feishu_config.encrypt_key = ""
    feishu_config.webhook_skip_signature_verify = False
    return config


class TestVerifySignature:
    """Test signature verification."""

    def test_verify_signature_valid(self):
        """Test signature verification with valid signature."""
        encrypt_key = "test_key"
        timestamp = "1234567890"
        nonce = "test_nonce"
        body = '{"test": "data"}'

        # Generate expected signature using Lark algorithm:
        # SHA256(timestamp + nonce + encrypt_key + body) as hex
        content = f"{timestamp}{nonce}{encrypt_key}{body}"
        expected_signature = hashlib.sha256(
            content.encode("utf-8"),
        ).hexdigest()

        # Verify
        result = verify_signature(
            encrypt_key,
            timestamp,
            nonce,
            body,
            expected_signature,
        )
        assert result is True

    def test_verify_signature_invalid(self):
        """Test signature verification with invalid signature."""
        encrypt_key = "test_key"
        timestamp = "1234567890"
        nonce = "test_nonce"
        body = '{"test": "data"}'
        wrong_signature = "wrong_signature"

        result = verify_signature(
            encrypt_key,
            timestamp,
            nonce,
            body,
            wrong_signature,
        )
        assert result is False

    def test_verify_signature_no_key(self):
        """Test signature verification with no key (should pass)."""
        result = verify_signature(
            "",
            "timestamp",
            "nonce",
            "body",
            "signature",
        )
        assert result is True


class TestChallengeVerification:
    """Test challenge verification endpoint."""

    def test_challenge_response(self, client):
        """Test URL verification challenge response."""
        challenge = "test_challenge_123"
        payload = {
            "type": "url_verification",
            "challenge": challenge,
        }

        response = client.post(
            "/webhook/feishu",
            json=payload,
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"challenge": challenge}


class TestWebhookEventHandling:
    """Test webhook event handling."""

    def test_webhook_disabled(self, client, mock_config):
        """Test webhook returns 503 when disabled."""
        mock_config.channels.feishu.webhook_enabled = False

        with patch(
            "copaw.app.routers.feishu_webhook._get_feishu_config",
            return_value=mock_config.channels.feishu,
        ):
            payload = {
                "schema": "2.0",
                "header": {"event_id": "test_event"},
                "event": {"message": {}},
            }

            response = client.post("/webhook/feishu", json=payload)

            assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
            assert "not enabled" in response.json()["detail"].lower()

    def test_invalid_signature(self, client, mock_config):
        """Test webhook returns 403 for invalid signature."""
        mock_config.channels.feishu.webhook_verification_token = (
            "correct_token"
        )

        with patch(
            "copaw.app.routers.feishu_webhook._get_feishu_config",
            return_value=mock_config.channels.feishu,
        ):
            payload = {
                "schema": "2.0",
                "header": {"event_id": "test_event"},
                "event": {"message": {}},
            }

            response = client.post(
                "/webhook/feishu",
                json=payload,
                headers={
                    "X-Lark-Request-Timestamp": "1234567890",
                    "X-Lark-Request-Nonce": "nonce",
                    "X-Lark-Signature": "invalid_signature",
                },
            )

            assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_invalid_json(self, client):
        """Test webhook returns 400 for invalid JSON."""
        response = client.post(
            "/webhook/feishu",
            data="invalid json",
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_channel_not_found(self, client, mock_config):
        """Test webhook returns 503 when Feishu channel not found."""
        # Mock empty channels
        app = client.app
        app.state.channel_manager = MagicMock()
        app.state.channel_manager.channels = {}

        with patch(
            "copaw.app.routers.feishu_webhook._get_feishu_config",
            return_value=mock_config.channels.feishu,
        ):
            payload = {
                "schema": "2.0",
                "header": {"event_id": "test_event"},
                "event": {
                    "message": {
                        "message_id": "test_msg",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": '{"text": "hello"}',
                    },
                    "sender": {
                        "sender_id": {"open_id": "test_user"},
                        "sender_type": "user",
                    },
                },
            }

            response = client.post("/webhook/feishu", json=payload)

            assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
            assert "not available" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_successful_event_dispatch(self, client, mock_config):
        """Test successful event dispatch to channel."""
        # Setup mock channel
        mock_channel = MagicMock()
        mock_channel.channel = "feishu"
        mock_channel.handle_webhook_event = AsyncMock()

        app = client.app
        app.state.channel_manager = MagicMock()
        app.state.channel_manager.channels = {"feishu": mock_channel}

        with patch(
            "copaw.app.routers.feishu_webhook._get_feishu_config",
            return_value=mock_config.channels.feishu,
        ):
            payload = {
                "schema": "2.0",
                "header": {"event_id": "test_event_123"},
                "event": {
                    "message": {
                        "message_id": "om_test_123",
                        "chat_id": "oc_test_chat",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": '{"text": "hello from webhook"}',
                    },
                    "sender": {
                        "sender_id": {"open_id": "ou_test_user"},
                        "sender_type": "user",
                        "name": "Test User",
                    },
                },
            }

            response = client.post("/webhook/feishu", json=payload)

            assert response.status_code == status.HTTP_200_OK
            assert response.json() == {"code": 0, "msg": "success"}
            mock_channel.handle_webhook_event.assert_called_once()


class TestHealthEndpoint:
    """Test health check endpoint."""

    def test_health_check(self, client):
        """Test health check returns correct status."""
        response = client.get("/webhook/feishu/health")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "ok"
        assert "webhook_enabled" in data


class TestWebhookEventFormat:
    """Test webhook event format conversion."""

    @pytest.mark.asyncio
    async def test_text_message_format(self):
        """Test text message format conversion."""
        from copaw.app.channels.feishu.channel import FeishuChannel

        channel = FeishuChannel(
            process=MagicMock(),
            enabled=True,
            app_id="test_app_id",
            app_secret="test_app_secret",
            bot_prefix="test",
        )
        channel._enqueue = MagicMock()

        # Mock _add_reaction to avoid API calls
        channel._add_reaction = AsyncMock()

        payload = {
            "event": {
                "message": {
                    "message_id": "om_test_msg",
                    "chat_id": "oc_test_chat",
                    "chat_type": "p2p",
                    "message_type": "text",
                    "content": '{"text": "Test message"}',
                },
                "sender": {
                    "sender_id": {"open_id": "ou_test_user"},
                    "sender_type": "user",
                    "name": "Test User",
                },
            },
        }

        await channel.handle_webhook_event(payload)

        # Verify the event was processed
        channel._enqueue.assert_called_once()
        native = channel._enqueue.call_args[0][0]
        assert native["channel_id"] == "feishu"
        assert "Test User" in native["sender_id"]
        assert native["meta"]["feishu_message_id"] == "om_test_msg"
        assert native["meta"]["feishu_chat_type"] == "p2p"

    @pytest.mark.asyncio
    async def test_group_message_format(self):
        """Test group message format conversion."""
        from copaw.app.channels.feishu.channel import FeishuChannel

        channel = FeishuChannel(
            process=MagicMock(),
            enabled=True,
            app_id="test_app_id",
            app_secret="test_app_secret",
            bot_prefix="test",
        )
        channel._enqueue = MagicMock()
        channel._add_reaction = AsyncMock()

        payload = {
            "event": {
                "message": {
                    "message_id": "om_test_msg",
                    "chat_id": "oc_group_chat",
                    "chat_type": "group",
                    "message_type": "text",
                    "content": '{"text": "Group message"}',
                },
                "sender": {
                    "sender_id": {"open_id": "ou_test_user"},
                    "sender_type": "user",
                    "name": "Test User",
                },
            },
        }

        await channel.handle_webhook_event(payload)

        native = channel._enqueue.call_args[0][0]
        assert native["meta"]["feishu_chat_type"] == "group"
        assert native["meta"]["feishu_receive_id_type"] == "chat_id"

    @pytest.mark.asyncio
    async def test_empty_event(self):
        """Test handling of empty event."""
        from copaw.app.channels.feishu.channel import FeishuChannel

        channel = FeishuChannel(
            process=MagicMock(),
            enabled=True,
            app_id="test_app_id",
            app_secret="test_app_secret",
            bot_prefix="test",
        )
        channel._enqueue = MagicMock()

        # Empty event
        payload = {"event": {}}

        await channel.handle_webhook_event(payload)

        # Should not call enqueue
        channel._enqueue.assert_not_called()

    @pytest.mark.asyncio
    async def test_bot_message_filtered(self):
        """Test that bot messages are filtered out."""
        from copaw.app.channels.feishu.channel import FeishuChannel

        channel = FeishuChannel(
            process=MagicMock(),
            enabled=True,
            app_id="test_app_id",
            app_secret="test_app_secret",
            bot_prefix="test",
        )
        channel._enqueue = MagicMock()
        channel._add_reaction = AsyncMock()

        payload = {
            "event": {
                "message": {
                    "message_id": "om_test_msg",
                    "chat_id": "oc_test_chat",
                    "chat_type": "p2p",
                    "message_type": "text",
                    "content": '{"text": "Bot message"}',
                },
                "sender": {
                    "sender_id": {"open_id": "ou_bot_user"},
                    "sender_type": "bot",  # Bot sender
                    "name": "Bot",
                },
            },
        }

        await channel.handle_webhook_event(payload)

        # Should not call enqueue for bot messages
        channel._enqueue.assert_not_called()


class TestDecryptBody:
    """Test body decryption."""

    def test_decrypt_empty(self):
        """Test decrypting empty body."""
        result = decrypt_body("key", "")
        assert result == ""

    def test_decrypt_invalid_data(self):
        """Test decrypt with invalid data raises error."""
        # Invalid encrypted data (too short for IV) should raise ValueError
        with pytest.raises(ValueError):
            decrypt_body("key", base64.b64encode(b"test").decode())
