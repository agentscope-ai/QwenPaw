# -*- coding: utf-8 -*-
"""
Voice Channel Contract Test

Ensures VoiceChannel satisfies all BaseChannel contracts.
When BaseChannel changes, this test validates VoiceChannel still complies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock


from tests.contract.channels import ChannelContractTest

if TYPE_CHECKING:
    from qwenpaw.app.channels.base import BaseChannel


class TestVoiceChannelContract(ChannelContractTest):
    """
    Contract tests for VoiceChannel.

    This validates that VoiceChannel properly implements all BaseChannel
    abstract methods and maintains interface compatibility.
    """

    def create_instance(self) -> "BaseChannel":
        """Provide a VoiceChannel instance for contract testing."""
        from qwenpaw.app.channels.voice.channel import VoiceChannel

        process = AsyncMock()

        # VoiceChannel has a different constructor signature
        return VoiceChannel(
            process=process,
            on_reply_sent=None,
            show_tool_details=False,
            filter_tool_messages=True,
            filter_thinking=False,
        )
