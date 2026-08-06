# -*- coding: utf-8 -*-
import json

import pytest
from agentscope.message import Msg, TextBlock

from qwenpaw.runtime.envelope import Envelope
from qwenpaw.schemas import RunStatus


@pytest.mark.asyncio
async def test_append_artifact_manifest_emits_tool_pair() -> None:
    envelope = Envelope(session_id="chat-1")
    manifest = {
        "version": 1,
        "agent_id": "analyst",
        "chat_id": "chat-1",
        "turn_id": "turn-1",
        "artifacts": [],
        "changes": [],
        "truncated": False,
    }

    events = [
        event async for event in envelope.append_artifact_manifest(manifest)
    ]

    assert [event.type.value for event in events] == [
        "plugin_call",
        "plugin_call_output",
    ]
    call_data = events[0].content[0].data
    output_data = events[1].content[0].data
    assert call_data["name"] == "workspace_artifacts"
    assert output_data["call_id"] == call_data["call_id"]
    assert json.loads(output_data["output"]) == manifest


@pytest.mark.asyncio
async def test_command_artifacts_precede_single_response_completion() -> None:
    envelope = Envelope(session_id="chat-1")
    command = Msg(
        name="assistant",
        role="assistant",
        content=[TextBlock(type="text", text="History exported")],
    )
    manifest = {
        "version": 1,
        "agent_id": "analyst",
        "chat_id": "chat-1",
        "turn_id": "turn-1",
        "artifacts": [],
        "changes": [],
        "truncated": False,
    }

    command_events = [event async for event in envelope.from_msg(command)]
    artifact_events = [
        event async for event in envelope.append_artifact_manifest(manifest)
    ]
    final_events = [event async for event in envelope.finalize()]
    events = command_events + artifact_events + final_events

    assert not any(
        getattr(event, "object", None) == "response"
        and event.status == RunStatus.Completed
        for event in command_events
    )
    assert [event.type.value for event in artifact_events] == [
        "plugin_call",
        "plugin_call_output",
    ]
    completed_responses = [
        event
        for event in events
        if getattr(event, "object", None) == "response"
        and event.status == RunStatus.Completed
    ]
    assert completed_responses == [events[-1]]
    assert [item.type.value for item in events[-1].output] == [
        "message",
        "plugin_call",
        "plugin_call_output",
    ]
