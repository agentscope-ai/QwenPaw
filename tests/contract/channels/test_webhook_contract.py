# -*- coding: utf-8 -*-
"""Webhook Channel Contract Test.

Ensures WebhookChannel satisfies all BaseChannel contracts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

from tests.contract.channels import ChannelContractTest

if TYPE_CHECKING:
    from qwenpaw.app.channels.base import BaseChannel


def create_mock_process_handler():
    """Create a mock process handler for channel testing."""
    mock = AsyncMock()

    async def mock_process(*_args, **_kwargs):
        from unittest.mock import MagicMock

        mock_event = MagicMock()
        mock_event.object = "message"
        mock_event.status = "completed"
        yield mock_event

    mock.side_effect = mock_process
    return mock


class TestWebhookChannelContract(ChannelContractTest):
    """WebhookChannel must satisfy ALL contracts."""

    def create_instance(self) -> "BaseChannel":
        """Provide a WebhookChannel instance for contract testing."""
        from qwenpaw.app.channels.webhook.channel import WebhookChannel

        process = create_mock_process_handler()
        return WebhookChannel(
            process=process,
            enabled=True,
            channel_id="default",
            outbound_url=None,
            secret=None,
        )

    def test_webhook_channel_attribute(self, instance):
        """Webhook-specific: channel is 'webhook'."""
        assert instance.channel == "webhook"

    def test_webhook_config_attribute(self, instance):
        """Webhook-specific: has config with channel_id."""
        assert hasattr(instance, "config")
        assert instance.config.channel_id == "default"

    def test_webhook_resolve_session_id_uses_channel_id(self, instance):
        """Webhook-specific: session id derived from channel_id."""
        result = instance.resolve_session_id("any_sender")
        assert result == "webhook:default"

    def test_webhook_resolve_session_id_honors_meta(self, instance):
        """Webhook-specific: explicit session_id in meta wins over channel_id."""
        result = instance.resolve_session_id(
            "any_sender",
            {"session_id": "abc"},
        )
        assert result == "webhook:abc"