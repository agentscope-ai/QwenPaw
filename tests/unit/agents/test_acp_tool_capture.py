# -*- coding: utf-8 -*-
"""Tests for QwenPaw envelope to ACP tool-call capture."""

from __future__ import annotations

from qwenpaw.agents.acp.server import _EnvelopeTracker
from qwenpaw.schemas import (
    ContentType,
    DataContent,
    FunctionCall,
    FunctionCallOutput,
    Message,
    MessageType,
    Role,
    RunStatus,
)


def _tool_call_message() -> Message:
    message = Message(
        id="message-call",
        type=MessageType.PLUGIN_CALL,
        role=Role.ASSISTANT,
        status=RunStatus.Completed,
        content=[
            DataContent(
                type=ContentType.DATA,
                data=FunctionCall(
                    call_id="call-1",
                    name="benchmark__lookup",
                    arguments='{"query": "documentation"}',
                ).model_dump(),
            ),
        ],
    )
    message.object = "message"
    return message


def _tool_result_message(state: str) -> Message:
    data = FunctionCallOutput(
        call_id="call-1",
        name="benchmark__lookup",
        output='{"answer": "found"}',
    ).model_dump()
    data["state"] = state
    message = Message(
        id="message-result",
        type=MessageType.PLUGIN_CALL_OUTPUT,
        role=Role.TOOL,
        status=RunStatus.Completed,
        content=[
            DataContent(
                type=ContentType.DATA,
                data=data,
            ),
        ],
    )
    message.object = "message"
    return message


def test_acp_tool_capture_preserves_id_name_arguments_and_output() -> None:
    tracker = _EnvelopeTracker()

    [start] = tracker.process(_tool_call_message())
    [result] = tracker.process(_tool_result_message("success"))

    assert start.tool_call_id == "call-1"
    assert start.title == "benchmark__lookup"
    assert start.status == "in_progress"
    assert start.raw_input == {"query": "documentation"}
    assert result.tool_call_id == "call-1"
    assert result.status == "completed"
    assert result.raw_output == '{"answer": "found"}'
    assert result.content[0].content.text == '{"answer": "found"}'


def test_acp_tool_capture_marks_unsuccessful_results_failed() -> None:
    tracker = _EnvelopeTracker()

    for state in ("error", "denied", "interrupted"):
        [result] = tracker.process(_tool_result_message(state))
        assert result.tool_call_id == "call-1"
        assert result.status == "failed"
