import json

import pytest

from qwenpaw.runtime.envelope import Envelope


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
