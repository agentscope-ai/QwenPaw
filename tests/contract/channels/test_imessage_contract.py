# -*- coding: utf-8 -*-
"""
iMessage Channel Contract Test

Ensures IMessageChannel satisfies all BaseChannel contracts.
When BaseChannel changes, this test validates IMessageChannel still complies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock


from tests.contract.channels import ChannelContractTest

if TYPE_CHECKING:
    from qwenpaw.app.channels.base import BaseChannel


class TestIMessageChannelContract(ChannelContractTest):
    """
    Contract tests for IMessageChannel.

    This validates that IMessageChannel properly implements all BaseChannel
    abstract methods and maintains interface compatibility.
    """

    def create_instance(self) -> "BaseChannel":
        """Provide an IMessageChannel instance for contract testing."""
        from qwenpaw.app.channels.imessage.channel import IMessageChannel

        process = AsyncMock()

        # IMessageChannel requires database path and poll interval
        return IMessageChannel(
            process=process,
            enabled=True,
            db_path="~/Library/Messages/chat.db",
            poll_sec=5.0,
            bot_prefix="[Test]",
            show_tool_details=False,
            filter_tool_messages=True,
        )
