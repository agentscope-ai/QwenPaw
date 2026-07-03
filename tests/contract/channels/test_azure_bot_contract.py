# -*- coding: utf-8 -*-
"""Azure Bot Channel Contract Test.

Ensures AzureBotChannel satisfies all BaseChannel contracts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

from tests.contract.channels import ChannelContractTest

if TYPE_CHECKING:
    from qwenpaw.app.channels.base import BaseChannel


def create_mock_process_handler():
    """Create a mock process handler for channel testing."""
    mock = AsyncMock()

    async def mock_process(*_args, **_kwargs):
        mock_event = MagicMock()
        mock_event.object = "message"
        mock_event.status = "completed"
        yield mock_event

    mock.side_effect = mock_process
    return mock


class TestAzureBotChannelContract(ChannelContractTest):
    """AzureBotChannel must satisfy ALL contracts."""

    def create_instance(self) -> "BaseChannel":
        """Provide an AzureBotChannel instance for contract testing."""
        from qwenpaw.app.channels.azure_bot.channel import AzureBotChannel

        process = create_mock_process_handler()
        return AzureBotChannel(
            process=process,
            enabled=True,
            app_id="test-app-id",
            app_password="test-password",
            tenant_id="test-tenant-id",
            http_host="127.0.0.1",
            http_port=13978,
        )

    def test_azure_bot_specific_attributes(self, instance):
        """Azure Bot-specific: has app_id and tenant_id."""
        assert hasattr(instance, "_app_id")
        assert hasattr(instance, "_tenant_id")
        assert instance._app_id == "test-app-id"
        assert instance._tenant_id == "test-tenant-id"

    def test_azure_bot_channel_name(self, instance):
        """Azure Bot channel name should be 'azure_bot'."""
        assert instance.channel == "azure_bot"

    def test_azure_bot_uses_manager_queue(self, instance):
        """Azure Bot should use manager queue."""
        assert instance.uses_manager_queue is True
