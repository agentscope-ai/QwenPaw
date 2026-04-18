# -*- coding: utf-8 -*-
"""
Mattermost Channel Contract Test

Ensures MattermostChannel satisfies all BaseChannel contracts.
When BaseChannel changes, this test validates MattermostChannel still complies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock


from tests.contract.channels import ChannelContractTest

if TYPE_CHECKING:
    from qwenpaw.app.channels.base import BaseChannel


class TestMattermostChannelContract(ChannelContractTest):
    """
    Contract tests for MattermostChannel.

    This validates that MattermostChannel properly implements all BaseChannel
    abstract methods and maintains interface compatibility.
    """

    def create_instance(self) -> "BaseChannel":
        """Provide a MattermostChannel instance for contract testing."""
        from qwenpaw.app.channels.mattermost.channel import MattermostChannel

        process = AsyncMock()

        # MattermostChannel requires server URL and bot token
        return MattermostChannel(
            process=process,
            enabled=True,
            url="https://mattermost.example.com",
            bot_token="test_bot_token_12345",
            bot_prefix="[Test]",
            show_tool_details=False,
            filter_tool_messages=True,
        )
