# -*- coding: utf-8 -*-
"""Contract tests for the WeCom channel."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from qwenpaw.app.channels.renderer import ChannelDisplayConfig

from tests.contract.channels import ChannelContractTest

if TYPE_CHECKING:
    from qwenpaw.app.channels.base import BaseChannel


class TestWecomChannelContract(ChannelContractTest):
    """Ensure WecomChannel satisfies the common channel contract."""

    @pytest.fixture(autouse=True)
    def _setup_paths(self, tmp_path):
        """Keep channel files isolated from the user's workspace."""
        self._workspace_dir = tmp_path / "workspace"
        self._workspace_dir.mkdir()
        self._media_dir = self._workspace_dir / "media"
        self._media_dir.mkdir()

    def create_instance(self) -> "BaseChannel":
        """Create a disabled WecomChannel with an async process mock."""
        from qwenpaw.app.channels.wecom.channel import WecomChannel

        return WecomChannel(
            process=AsyncMock(),
            enabled=False,
            bot_id="test_bot_id",
            secret="test_secret",
            media_dir=str(self._media_dir),
            workspace_dir=self._workspace_dir,
            display_config=ChannelDisplayConfig(
                show_tool_calls=False,
                show_tool_results=False,
            ),
        )
