# -*- coding: utf-8 -*-
"""
Matrix Channel Contract Test

Ensures MatrixChannel satisfies all BaseChannel contracts.
When BaseChannel changes, this test validates MatrixChannel still complies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock


from tests.contract.channels import ChannelContractTest

if TYPE_CHECKING:
    from qwenpaw.app.channels.base import BaseChannel


class TestMatrixChannelContract(ChannelContractTest):
    """
    Contract tests for MatrixChannel.

    This validates that MatrixChannel properly implements all BaseChannel
    abstract methods and maintains interface compatibility.
    """

    def create_instance(self) -> "BaseChannel":
        """Provide a MatrixChannel instance for contract testing."""
        from qwenpaw.app.channels.matrix.channel import MatrixChannel

        from qwenpaw.app.channels.matrix.channel import MatrixChannelConfig

        process = AsyncMock()
        config = MatrixChannelConfig(
            raw={
                "enabled": True,
                "homeserver": "https://matrix.example.com",
                "access_token": "test_token_12345",
                "bot_prefix": "[Test]",
            },
        )
        return MatrixChannel(
            process=process,
            config=config,
            show_tool_details=False,
            filter_tool_messages=True,
        )
