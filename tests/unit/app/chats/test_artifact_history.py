# -*- coding: utf-8 -*-
import json

from qwenpaw.app.chats.api import _get_workspace_artifact_manifests
from qwenpaw.app.chats.utils import (
    artifact_manifest_to_messages,
    merge_artifact_manifests,
)
from qwenpaw.schemas import Message, MessageType


def test_history_reads_manifests_from_persisted_agent_state() -> None:
    manifests = [{"version": 1, "turn_id": "turn-1"}]
    state = {"agent": {"workspace_artifact_manifests": manifests}}

    result = _get_workspace_artifact_manifests(state, state["agent"])

    assert result == manifests


def test_history_keeps_root_manifest_compatibility() -> None:
    manifests = [{"version": 1, "turn_id": "turn-1"}]

    result = _get_workspace_artifact_manifests(
        {"workspace_artifact_manifests": manifests},
        {},
    )

    assert result == manifests


def test_artifact_manifest_history_uses_tool_pair() -> None:
    manifest = {
        "version": 1,
        "agent_id": "analyst",
        "chat_id": "chat-1",
        "turn_id": "turn-1",
        "artifacts": [],
        "changes": [],
        "truncated": False,
    }

    messages = artifact_manifest_to_messages(manifest)

    assert [message.type.value for message in messages] == [
        "plugin_call",
        "plugin_call_output",
    ]
    output = messages[1].content[0].data["output"]
    assert json.loads(output) == manifest


def test_merge_artifact_manifests_preserves_turn_order() -> None:
    first = Message(type=MessageType.MESSAGE, role="assistant")
    first.metadata = {"timestamp": "2026-08-03T10:00:00+00:00"}
    second = Message(type=MessageType.MESSAGE, role="assistant")
    second.metadata = {"timestamp": "2026-08-03T11:00:00+00:00"}
    manifest = {
        "version": 1,
        "agent_id": "analyst",
        "chat_id": "chat-1",
        "turn_id": "turn-1",
        "created_at": "2026-08-03T10:30:00+00:00",
        "artifacts": [],
        "changes": [],
        "truncated": False,
    }

    merged = merge_artifact_manifests([first, second], [manifest])

    assert [message.type.value for message in merged] == [
        "message",
        "plugin_call",
        "plugin_call_output",
        "message",
    ]
