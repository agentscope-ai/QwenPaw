# -*- coding: utf-8 -*-
"""Tests for AsMsgHandler media token estimates."""

import base64

import pytest
from agentscope.message import Base64Source, DataBlock, Msg

from qwenpaw.agents.utils.as_msg_handler import AsMsgHandler
from qwenpaw.agents.utils.estimate_token_counter import EstimatedTokenCounter


@pytest.mark.asyncio
async def test_base64_image_does_not_count_payload_as_text_tokens():
    payload = base64.b64encode(b"\x00" * (2 * 1024 * 1024)).decode("ascii")
    msg = Msg(
        name="user",
        role="user",
        content=[
            DataBlock(
                source=Base64Source(media_type="image/png", data=payload),
            ),
        ],
    )
    stat = await AsMsgHandler(EstimatedTokenCounter()).stat_message(msg)
    # Old heuristic was len(base64)//4 ≈ 700k and filled the context ring.
    assert 0 < stat.total_tokens < 10_000
