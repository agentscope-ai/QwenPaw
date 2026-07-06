# -*- coding: utf-8 -*-
"""
Zalo Channel Contract Test

Ensures ZaloChannel satisfies all BaseChannel contracts.
When BaseChannel changes, this test validates ZaloChannel still complies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock


from tests.contract.channels import ChannelContractTest

if TYPE_CHECKING:
    from qwenpaw.app.channels.base import BaseChannel


class TestZaloChannelContract(ChannelContractTest):
    """
    Contract tests for ZaloChannel.

    Validates that ZaloChannel properly implements all BaseChannel
    abstract methods and maintains interface compatibility.
    """

    def create_instance(self) -> "BaseChannel":
        """Provide a ZaloChannel instance for contract testing."""
        from qwenpaw.app.channels.zalo.channel import ZaloChannel

        process = AsyncMock()

        return ZaloChannel(
            process=process,
            bot_token="test_token_1234567890",
            secret_token="test-secret-min-8-chars",
            poll_interval=30,
            show_typing=False,
            filter_tool_messages=True,
            filter_thinking=True,
        )
