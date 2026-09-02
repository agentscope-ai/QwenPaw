# -*- coding: utf-8 -*-
"""Contract tests for the WeChat channel."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from qwenpaw.app.channels.renderer import ChannelDisplayConfig

from tests.contract.channels import ChannelContractTest

if TYPE_CHECKING:
    from qwenpaw.app.channels.base import BaseChannel


class TestWeChatChannelContract(ChannelContractTest):
    """Ensure WeChatChannel satisfies the common channel contract."""

    @pytest.fixture(autouse=True)
    def _setup_paths(self, tmp_path):
        """Keep channel files isolated from the user's workspace."""
        self._workspace_dir = tmp_path / "workspace"
        self._workspace_dir.mkdir()
        self._media_dir = self._workspace_dir / "media"
        self._media_dir.mkdir()
        self._token_file = self._workspace_dir / "wechat_token"

    def create_instance(self) -> "BaseChannel":
        """Create a disabled WeChatChannel with an async process mock."""
        from qwenpaw.app.channels.wechat.channel import WeChatChannel

        return WeChatChannel(
            process=AsyncMock(),
            enabled=False,
            bot_token="",
            bot_token_file=str(self._token_file),
            media_dir=str(self._media_dir),
            workspace_dir=self._workspace_dir,
            display_config=ChannelDisplayConfig(
                show_tool_calls=False,
                show_tool_results=False,
            ),
        )
