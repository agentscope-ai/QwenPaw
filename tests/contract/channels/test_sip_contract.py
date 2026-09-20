# -*- coding: utf-8 -*-
"""Contract tests for the SIP channel."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

from qwenpaw.app.channels.renderer import ChannelDisplayConfig

from tests.contract.channels import ChannelContractTest

if TYPE_CHECKING:
    from qwenpaw.app.channels.base import BaseChannel


class TestSIPChannelContract(ChannelContractTest):
    """Ensure SIPChannel satisfies the common channel contract."""

    def create_instance(self) -> "BaseChannel":
        """Create an unconfigured SIPChannel with an async process mock."""
        from qwenpaw.app.channels.sip import SIPChannel

        return SIPChannel(
            process=AsyncMock(),
            display_config=ChannelDisplayConfig(
                show_tool_calls=False,
                show_tool_results=False,
            ),
        )
