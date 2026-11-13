# -*- coding: utf-8 -*-
"""Tests for AsMsgHandler media token estimates."""

# pylint: disable=protected-access

import base64

import pytest
from agentscope.message import (
    Base64Source,
    DataBlock,
    Msg,
)

from qwenpaw.agents.utils.as_msg_handler import AsMsgHandler
from qwenpaw.agents.utils.estimate_token_counter import EstimatedTokenCounter
from qwenpaw.agents.utils.media_token_estimate import (
    IMAGE_FALLBACK_TOKENS,
    VIDEO_FALLBACK_TOKENS,
    estimate_inline_media_tokens,
)


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


@pytest.mark.asyncio
async def test_tool_result_blocks_dispatch_by_mime():
    payload = base64.b64encode(b"\x00" * 4096).decode("ascii")
    handler = AsMsgHandler(EstimatedTokenCounter())
    png = await handler._format_tool_result_output(
        [
            {
                "type": "data",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": payload,
                },
            },
        ],
    )
    video = await handler._format_tool_result_output(
        [
            {
                "type": "data",
                "source": {
                    "type": "base64",
                    "media_type": "video/mp4",
                    "data": payload,
                },
            },
        ],
    )
    pdf = await handler._format_tool_result_output(
        [
            {
                "type": "data",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": payload,
                },
            },
        ],
    )
    assert png[1] == IMAGE_FALLBACK_TOKENS
    assert video[1] == VIDEO_FALLBACK_TOKENS
    assert pdf[1] != video[1]
    assert png[1] != len(payload) // 4


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind",
    ("string", "text_block", "scheme_upper", "base64_upper"),
)
async def test_tool_result_text_data_url_not_counted_as_text(kind):
    payload = "A" * (1024 * 1024)
    if kind == "scheme_upper":
        data_url = f"DATA:image/png;base64,{payload}"
    elif kind == "base64_upper":
        data_url = f"data:image/png;BASE64,{payload}"
    else:
        data_url = f"data:image/png;base64,{payload}"
    handler = AsMsgHandler(EstimatedTokenCounter())
    if kind == "text_block":
        output = [{"type": "text", "text": data_url}]
    else:
        output = data_url
    _, tokens = await handler._format_tool_result_output(output)
    expected = estimate_inline_media_tokens("image/png", payload)
    assert tokens == expected
    assert tokens < 10_000
    assert tokens != len(data_url) // 4
