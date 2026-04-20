# -*- coding: utf-8 -*-
# pylint: disable=wrong-import-position
"""
WhatsApp Channel Contract Test

Ensures WhatsAppChannel satisfies all BaseChannel contracts.
When BaseChannel changes, this test validates WhatsAppChannel still complies.

Skipped automatically in environments where the optional ``neonize-qwenpaw``
dependency (declared under ``[project.optional-dependencies] whatsapp``) is
not installed — the test does NOT require users who install vanilla
``qwenpaw`` to pull in the WhatsApp runtime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

# The WhatsApp channel imports `neonize` at module load. Skip this whole
# contract module when the optional dep is not installed so the rest of
# the test suite runs cleanly in `pip install qwenpaw[dev]` environments.
pytest.importorskip("neonize")

from tests.contract.channels import ChannelContractTest  # noqa: E402

if TYPE_CHECKING:
    from qwenpaw.app.channels.base import BaseChannel


class TestWhatsAppChannelContract(ChannelContractTest):
    """
    Contract tests for WhatsAppChannel.

    This validates that WhatsAppChannel properly implements all BaseChannel
    abstract methods and maintains interface compatibility.
    """

    def create_instance(self) -> "BaseChannel":
        """Provide a WhatsAppChannel instance for contract testing."""
        from qwenpaw.app.channels.whatsapp.channel import WhatsAppChannel

        process = AsyncMock()

        return WhatsAppChannel(
            process=process,
            enabled=False,
            auth_dir="",
            send_read_receipts=False,
            text_chunk_limit=4096,
            self_chat_mode=False,
            ack_reaction_thinking="",
            ack_reaction_done="",
            ack_reaction_error="",
            show_tool_details=False,
            filter_tool_messages=True,
        )
