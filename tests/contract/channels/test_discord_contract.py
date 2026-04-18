# -*- coding: utf-8 -*-
"""
Discord Channel Contract Test

Ensures DiscordChannel satisfies all BaseChannel contracts.
When BaseChannel changes, this test validates DiscordChannel still complies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock


from tests.contract.channels import ChannelContractTest

if TYPE_CHECKING:
    from qwenpaw.app.channels.base import BaseChannel


class TestDiscordChannelContract(ChannelContractTest):
    """
    Contract tests for DiscordChannel.

    This validates that DiscordChannel properly implements all BaseChannel
    abstract methods and maintains interface compatibility.
    """

    def create_instance(self) -> "BaseChannel":
        """Provide a DiscordChannel instance for contract testing."""
        from qwenpaw.app.channels.discord_.channel import DiscordChannel

        process = AsyncMock()

        return DiscordChannel(
            process=process,
            enabled=True,
            token="test_token",
            http_proxy="",
            http_proxy_auth="",
            bot_prefix="[Test]",
            show_tool_details=False,
            filter_tool_messages=True,
        )
