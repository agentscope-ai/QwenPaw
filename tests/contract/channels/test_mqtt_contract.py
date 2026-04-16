# -*- coding: utf-8 -*-
"""
MQTT Channel Contract Test

Ensures MQTTChannel satisfies all BaseChannel contracts.
When BaseChannel changes, this test validates MQTTChannel still complies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock


from tests.contract.channels import ChannelContractTest

if TYPE_CHECKING:
    from qwenpaw.app.channels.base import BaseChannel


class TestMQTTChannelContract(ChannelContractTest):
    """
    Contract tests for MQTTChannel.

    This validates that MQTTChannel properly implements all BaseChannel
    abstract methods and maintains interface compatibility.
    """

    def create_instance(self) -> "BaseChannel":
        """Provide a MQTTChannel instance for contract testing."""
        from qwenpaw.app.channels.mqtt.channel import MQTTChannel

        process = AsyncMock()

        # MQTTChannel requires connection parameters
        return MQTTChannel(
            process=process,
            enabled=True,
            host="localhost",
            port=1883,
            transport="tcp",
            username="test_user",
            password="test_pass",
            subscribe_topic="copaw/in",
            publish_topic="copaw/out",
            bot_prefix="[Test]",
            show_tool_details=False,
            filter_tool_messages=True,
        )
