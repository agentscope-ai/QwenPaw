# -*- coding: utf-8 -*-
"""WeChat channel contract tests."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

from qwenpaw.app.channels.renderer import ChannelDisplayConfig

from tests.contract.channels import ChannelContractTest

if TYPE_CHECKING:
    from qwenpaw.app.channels.base import BaseChannel


class TestWeChatChannelContract(ChannelContractTest):
    """Ensure WeChatChannel satisfies the BaseChannel contract."""

    def create_instance(self) -> "BaseChannel":
        """Provide a configured WeChat channel instance."""
        from qwenpaw.app.channels.wechat.channel import WeChatChannel

        return WeChatChannel(
            process=AsyncMock(),
            enabled=True,
            bot_token="test_token",
            bot_prefix="[Test]",
            display_config=ChannelDisplayConfig(
                show_tool_calls=False,
                show_tool_results=False,
            ),
        )
