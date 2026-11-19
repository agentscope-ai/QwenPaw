# -*- coding: utf-8 -*-
"""Verify live tool output stays bounded while the final output is complete."""

import pytest

from qwenpaw.plugins.harnesses import HarnessEvent, HarnessEventKind
from qwenpaw.runtime.backends.streaming import ToolStream
from qwenpaw.schemas import AgentResponse


@pytest.mark.parametrize("completion_supplies_output", [False, True])
def test_large_tool_output_keeps_live_payload_bounded(
    completion_supplies_output,
):
    response = AgentResponse()
    stream = ToolStream(response)
    stream.start(
        HarnessEvent(
            HarnessEventKind.TOOL_STARTED,
            item_id="tool",
            tool_name="shell",
        ),
    )
    chunks = [f"{index:02d}" * 512 for index in range(40)]
    progress = []
    for chunk in chunks:
        (event,) = stream.progress(
            HarnessEvent(
                HarnessEventKind.TOOL_PROGRESS,
                item_id="tool",
                text=chunk,
            ),
        )
        assert event.delta is False
        assert len(event.data["output"]) <= 4096
        progress.append(event.data["output"])

    assert progress[0] == chunks[0]
    assert progress[-1] == "".join(chunks[-4:])

    full_output = "".join(chunks)
    final_output = (
        "final: " + full_output if completion_supplies_output else ""
    )
    content, message = stream.complete(
        HarnessEvent(
            HarnessEventKind.TOOL_COMPLETED,
            item_id="tool",
            tool_name="shell",
            text=final_output,
        ),
    )
    expected = final_output or full_output
    assert content.data["output"] == expected
    assert message.content[0].data["output"] == expected
    assert response.output[-1].content[0].data["output"] == expected
