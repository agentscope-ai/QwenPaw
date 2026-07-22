# -*- coding: utf-8 -*-
"""Slack Channel Contract Test.

Ensures SlackChannel satisfies all BaseChannel contracts.
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


class TestSlackChannelContract(ChannelContractTest):
    """SlackChannel must satisfy ALL contracts."""

    def create_instance(self) -> "BaseChannel":
        """Provide a SlackChannel instance for contract testing."""
        from qwenpaw.app.channels.slack.channel import SlackChannel

        process = create_mock_process_handler()
        return SlackChannel(
            process=process,
            enabled=True,
            bot_token="xoxb-test-token",
            app_token="xapp-test-token",
            bot_prefix="",
            proxy="",
            streaming_enabled=False,
        )

    def test_slack_specific_attributes(self, instance):
        """Slack-specific: has bot_token and app_token."""
        assert hasattr(instance, "bot_token")
        assert hasattr(instance, "app_token")
        assert instance.bot_token == "xoxb-test-token"
        assert instance.app_token == "xapp-test-token"

    def test_slack_media_dir_exists(self, instance):
        """Slack-specific: media_dir is set and is a Path."""
        from pathlib import Path

        assert hasattr(instance, "media_dir")
        assert isinstance(instance.media_dir, Path)
