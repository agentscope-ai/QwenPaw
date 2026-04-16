# -*- coding: utf-8 -*-
"""
Telegram Channel Contract Test

Ensures TelegramChannel satisfies all BaseChannel contracts.
When BaseChannel changes, this test validates TelegramChannel still complies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock


from tests.contract.channels import ChannelContractTest

if TYPE_CHECKING:
    from qwenpaw.app.channels.base import BaseChannel


class TestTelegramChannelContract(ChannelContractTest):
    """
    Contract tests for TelegramChannel.

    This validates that TelegramChannel properly implements all BaseChannel
    abstract methods and maintains interface compatibility.
    """

    def create_instance(self) -> "BaseChannel":
        """Provide a TelegramChannel instance for contract testing."""
        from qwenpaw.app.channels.telegram.channel import TelegramChannel

        process = AsyncMock()

        return TelegramChannel(
            process=process,
            enabled=True,
            bot_token="test_token",
            http_proxy="",
            http_proxy_auth="",
            bot_prefix="[Test]",
            show_tool_details=False,
            filter_tool_messages=True,
        )
