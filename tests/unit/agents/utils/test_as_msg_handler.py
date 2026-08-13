# -*- coding: utf-8 -*-
"""Tests for AsMsgHandler media token estimates."""

# pylint: disable=protected-access

import base64
import io

import pytest
from agentscope.message import (
    Base64Source,
    DataBlock,
    Msg,
    ToolResultBlock,
)
from PIL import Image

from qwenpaw.agents.utils.as_msg_handler import AsMsgHandler
from qwenpaw.agents.utils.estimate_token_counter import EstimatedTokenCounter
from qwenpaw.agents.utils.media_token_estimate import (
    IMAGE_FALLBACK_TOKENS,
    VIDEO_FALLBACK_TOKENS,
    estimate_inline_media_tokens,
)


def _png_b64() -> str:
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), color=(0, 0, 0)).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


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
async def test_string_tool_result_data_url_not_counted_as_text():
    payload = _png_b64()
    data_url = f"data:image/png;base64,{payload}"
    msg = Msg(
        name="assistant",
        role="assistant",
        content=[
            ToolResultBlock(
                type="tool_result",
                id="t1",
                name="read_image",
                output=data_url,
            ),
        ],
    )
    stat = await AsMsgHandler(EstimatedTokenCounter()).stat_message(msg)
    expected = estimate_inline_media_tokens("image/png", payload)
    assert stat.total_tokens == expected
    assert stat.total_tokens < len(data_url) // 4
