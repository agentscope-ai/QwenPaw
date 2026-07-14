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

    This validates that ZaloChannel properly implements all BaseChannel
    abstract methods and maintains interface compatibility.
    """

    def create_instance(self) -> "BaseChannel":
        """Provide a ZaloChannel instance for contract testing."""
        from qwenpaw.app.channels.zalo.channel import ZaloChannel

        process = AsyncMock()

        return ZaloChannel(
            process=process,
            enabled=True,
            bot_token="test_zalo_token",
            api_base_url="https://bot.zalo.me",
            secret_token="",
            show_typing=True,
            poll_interval=30.0,
            max_retries=3,
            max_message_len=2000,
            share_session_in_group=True,
            show_tool_details=False,
            filter_tool_messages=True,
        )
