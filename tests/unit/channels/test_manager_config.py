# -*- coding: utf-8 -*-
"""ChannelManager config propagation tests."""

# pylint: disable=protected-access

from __future__ import annotations

from typing import Any

from qwenpaw.app.channels.manager import ChannelManager
from qwenpaw.config.config import ChannelConfig, Config, ConsoleConfig


async def _noop_process(_request: Any):
    if False:  # pylint: disable=using-constant-test
        yield None


def test_from_config_applies_aggregate_message_replies_to_channel():
    """Common channel config should reach the channel instance."""
    config = Config(
        channels=ChannelConfig(
            console=ConsoleConfig(
                enabled=True,
                aggregate_message_replies=True,
            ),
        ),
    )

    manager = ChannelManager.from_config(_noop_process, config)

    console = next(ch for ch in manager.channels if ch.channel == "console")
    assert console._aggregate_message_replies is True
