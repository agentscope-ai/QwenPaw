# -*- coding: utf-8 -*-
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from qwenpaw.app.chats.api import (
    _get_workspace_artifact_manifests,
    get_chat,
)
from qwenpaw.app.chats.models import ChatSpec
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


async def test_history_restores_version_two_project_manifest() -> None:
    manifest = {
        "version": 2,
        "agent_id": "analyst",
        "chat_id": "chat-1",
        "turn_id": "turn-1",
        "created_at": "2026-08-03T10:30:00+00:00",
        "artifacts": [
            {
                "path": "report.txt",
                "name": "report.txt",
                "extension": ".txt",
                "mime_type": "text/plain",
                "size": 12,
                "modified_ns": 34,
                "change": "created",
                "preview": "text",
                "root": "project",
            },
        ],
        "changes": [
            {
                "path": "report.txt",
                "change": "created",
                "root": "project",
            },
        ],
        "truncated": False,
    }
    chat = ChatSpec(
        id="chat-1",
        session_id="chat-1",
        user_id="user-1",
        channel="console",
    )
    manager = SimpleNamespace(get_chat=AsyncMock(return_value=chat))
    session = SimpleNamespace(
        get_session_state_dict=AsyncMock(
            return_value={
                "agent": {"workspace_artifact_manifests": [manifest]},
            },
        ),
    )
    workspace = SimpleNamespace(
        config=SimpleNamespace(backend="qwenpaw"),
        task_tracker=SimpleNamespace(
            get_status=AsyncMock(return_value="idle"),
        ),
    )

    history = await get_chat(
        "chat-1",
        mgr=manager,
        session=session,
        workspace=workspace,
    )

    output = history.messages[1].content[0].data["output"]
    restored = json.loads(output)
    assert restored["version"] == 2
    assert restored["artifacts"][0]["root"] == "project"


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


def test_merge_artifact_manifests_normalizes_timezones() -> None:
    before = Message(type=MessageType.MESSAGE, role="assistant")
    before.metadata = {"timestamp": "2026-08-03T14:00:00+08:00"}
    after = Message(type=MessageType.MESSAGE, role="assistant")
    after.metadata = {"timestamp": "2026-08-03T15:00:00+08:00"}
    manifest = {
        "version": 1,
        "agent_id": "analyst",
        "chat_id": "chat-1",
        "turn_id": "turn-2",
        "created_at": "2026-08-03T06:30:00+00:00",
        "artifacts": [],
        "changes": [],
        "truncated": False,
    }

    merged = merge_artifact_manifests([before, after], [manifest])

    assert [message.type.value for message in merged] == [
        "message",
        "plugin_call",
        "plugin_call_output",
        "message",
    ]


def test_merge_artifact_manifests_keeps_multiple_cards_in_order() -> None:
    message = Message(type=MessageType.MESSAGE, role="assistant")
    message.metadata = {"timestamp": "2026-08-03T12:00:00+00:00"}
    manifests = [
        {
            "version": 1,
            "agent_id": "analyst",
            "chat_id": "chat-1",
            "turn_id": "turn-2",
            "created_at": "2026-08-03T12:30:00+00:00",
            "artifacts": [],
            "changes": [],
            "truncated": False,
        },
        {
            "version": 1,
            "agent_id": "analyst",
            "chat_id": "chat-1",
            "turn_id": "turn-1",
            "created_at": "2026-08-03T12:15:00+00:00",
            "artifacts": [],
            "changes": [],
            "truncated": False,
        },
    ]

    merged = merge_artifact_manifests([message], manifests)

    turn_ids = [
        json.loads(item.content[0].data["output"])["turn_id"]
        for item in merged
        if item.type == MessageType.PLUGIN_CALL_OUTPUT
    ]
    assert turn_ids == ["turn-1", "turn-2"]
