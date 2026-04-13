# -*- coding: utf-8 -*-
"""
QQ Channel Contract Test

Ensures QQChannel satisfies all BaseChannel contracts.
When BaseChannel changes, this test validates QQChannel still complies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock


from tests.contract.channels import ChannelContractTest

if TYPE_CHECKING:
    from qwenpaw.app.channels.base import BaseChannel


class TestQQChannelContract(ChannelContractTest):
    """
    Contract tests for QQChannel.

    This validates that QQChannel properly implements all BaseChannel
    abstract methods and maintains interface compatibility.
    """

    def create_instance(self) -> "BaseChannel":
        """Provide a QQChannel instance for contract testing."""
        from qwenpaw.app.channels.qq.channel import QQChannel

        process = AsyncMock()

        return QQChannel(
            process=process,
            enabled=True,
            app_id="test_app_id",
            client_secret="test_secret",
            bot_prefix="[Test]",
            markdown_enabled=True,
            show_tool_details=False,
            filter_tool_messages=True,
        )
