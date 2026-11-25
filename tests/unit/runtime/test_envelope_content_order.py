# -*- coding: utf-8 -*-
"""Interleaved tool text/media remain ordered in completed and partial output."""

import json

import pytest
from agentscope.event import EventType
from qwenpaw.runtime.envelope import Envelope
from .test_envelope_metadata import _event, _translate


@pytest.mark.asyncio
async def test_interleaved_tool_output_and_base64_fragments():
    envelope = Envelope()

    async def send(kind, **fields):
        return await _translate(
            envelope,
            _event(kind, tool_call_id="call", **fields),
        )

    await send(EventType.TOOL_RESULT_START, tool_call_name="tool")
    await send(EventType.TOOL_RESULT_TEXT_DELTA, delta="be")
    await send(EventType.TOOL_RESULT_TEXT_DELTA, delta="fore")
    first = await send(
        EventType.TOOL_RESULT_DATA_DELTA,
        block_id="image",
        media_type="image/png",
        data="YW",
        url=None,
    )
    await send(EventType.TOOL_RESULT_TEXT_DELTA, delta="after")
    await send(
        EventType.TOOL_RESULT_DATA_DELTA,
        block_id="image",
        media_type="image/png",
        data="Jj",
        url=None,
    )
    partial = envelope.collect_tool_output()
    assert partial == {"call": "beforeafter"}
    completed = await send(EventType.TOOL_RESULT_END, state="success")
    output = json.loads(completed[-1]["content"][0]["data"]["output"])
    assert output == [
        {"type": "text", "text": "before"},
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": "YWJj",
            },
        },
        {"type": "text", "text": "after"},
    ]
    # An earlier emitted snapshot cannot grow when later chunks arrive.
    initial_output = json.loads(first[0]["data"]["output"])
    assert initial_output[1]["source"]["data"] == "YW"
    assert len(initial_output) == 2
    assert envelope.collect_tool_output() == {}
