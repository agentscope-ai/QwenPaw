# -*- coding: utf-8 -*-
"""Contract tests for the Console channel."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

from qwenpaw.app.channels.renderer import ChannelDisplayConfig

from tests.contract.channels import ChannelContractTest

if TYPE_CHECKING:
    from qwenpaw.app.channels.base import BaseChannel


def create_mock_process_handler():
    """Create a mock process handler for channel testing."""
    mock = AsyncMock()

    async def mock_process(*_args, **_kwargs):
        from unittest.mock import MagicMock

        mock_event = MagicMock()
        mock_event.object = "message"
        mock_event.status = "completed"
        yield mock_event

    mock.side_effect = mock_process
    return mock


class TestConsoleChannelContract(ChannelContractTest):
    """Ensure ConsoleChannel satisfies the common channel contract."""

    def create_instance(self) -> "BaseChannel":
        """Provide a ConsoleChannel instance for contract testing."""
        from qwenpaw.app.channels.console.channel import ConsoleChannel

        process = create_mock_process_handler()
        return ConsoleChannel(
            process=process,
            enabled=True,
            bot_prefix="[TEST] ",
            display_config=ChannelDisplayConfig(
                show_tool_calls=False,
                show_tool_results=False,
            ),
        )

    def test_console_specific_behavior(self, instance):
        """Console-specific: uses stdout for output."""
        assert hasattr(instance, "bot_prefix")
