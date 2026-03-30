# -*- coding: utf-8 -*-
from __future__ import annotations

from copaw.acp.projector import ACPEventProjector
from copaw.acp.types import AcpEvent


def test_projector_streams_assistant_chunks_until_finish() -> None:
    projector = ACPEventProjector(harness="opencode")

    first = projector.project(
        AcpEvent(
            type="assistant_chunk",
            chat_id="chat-1",
            session_id="sess-1",
            payload={"text": "hello"},
        ),
    )
    second = projector.project(
        AcpEvent(
            type="assistant_chunk",
            chat_id="chat-1",
            session_id="sess-1",
            payload={"text": " world"},
        ),
    )
    final = projector.project(
        AcpEvent(
            type="run_finished",
            chat_id="chat-1",
            session_id="sess-1",
            payload={},
        ),
    )

    assert len(first) == 1
    assert first[0][1] is False
    assert first[0][0].content[0]["text"] == "hello"

    assert len(second) == 1
    assert second[0][1] is False
    assert second[0][0].content[0]["text"] == "hello world"

    assert len(final) == 1
    assert final[0][1] is True
    assert final[0][0].content[0]["text"] == "hello world"


def test_projector_maps_tool_events_to_tool_messages() -> None:
    projector = ACPEventProjector(harness="qwen")

    messages = projector.project(
        AcpEvent(
            type="tool_start",
            chat_id="chat-1",
            session_id="sess-1",
            payload={
                "id": "tool-1",
                "name": "read_file",
                "input": {"path": "README.md"},
            },
        ),
    )

    assert len(messages) == 1
    msg, last = messages[0]
    assert last is True
    assert msg.role == "assistant"
    assert msg.content[0]["type"] == "tool_use"
    assert msg.content[0]["name"] == "read_file"


def test_projector_suppresses_intermediate_tool_updates() -> None:
    projector = ACPEventProjector(harness="opencode")

    update = projector.project(
        AcpEvent(
            type="tool_update",
            chat_id="chat-1",
            session_id="sess-1",
            payload={
                "id": "tool-1",
                "name": "read",
                "output": "in_progress",
                "status": "in_progress",
            },
        ),
    )
    end = projector.project(
        AcpEvent(
            type="tool_end",
            chat_id="chat-1",
            session_id="sess-1",
            payload={
                "id": "tool-1",
                "name": "read",
                "output": "final content",
                "status": "completed",
            },
        ),
    )

    assert not update
    assert len(end) == 1
    assert end[0][0].content[0]["type"] == "tool_result"
    assert end[0][0].content[0]["output"] == "final content"


def test_projector_finalize_flushes_pending_tool_update() -> None:
    projector = ACPEventProjector(harness="opencode")

    projector.project(
        AcpEvent(
            type="tool_update",
            chat_id="chat-1",
            session_id="sess-1",
            payload={
                "id": "tool-1",
                "name": "read",
                "output": "final content",
                "status": "completed",
            },
        ),
    )

    finalized = projector.finalize()

    assert len(finalized) == 1
    assert finalized[0][0].content[0]["type"] == "tool_result"
    assert finalized[0][0].content[0]["output"] == "final content"


def test_projector_suppresses_commands_and_usage_updates() -> None:
    projector = ACPEventProjector(harness="opencode")

    commands = projector.project(
        AcpEvent(
            type="commands_update",
            chat_id="chat-1",
            session_id="sess-1",
            payload={"commands": [{"name": "init"}, {"name": "review"}]},
        ),
    )
    usage = projector.project(
        AcpEvent(
            type="usage_update",
            chat_id="chat-1",
            session_id="sess-1",
            payload={"used": 123},
        ),
    )

    assert not commands
    assert not usage


def test_projector_hides_tool_messages_when_disabled() -> None:
    projector = ACPEventProjector(
        harness="opencode",
        show_tool_calls=False,
    )

    messages = projector.project(
        AcpEvent(
            type="tool_start",
            chat_id="chat-1",
            session_id="sess-1",
            payload={
                "id": "tool-1",
                "name": "read_file",
                "input": {"path": "README.md"},
            },
        ),
    )

    assert not messages


def test_projector_merges_pending_tool_update_into_tool_end() -> None:
    projector = ACPEventProjector(harness="opencode")

    projector.project(
        AcpEvent(
            type="tool_update",
            chat_id="chat-1",
            session_id="sess-1",
            payload={
                "id": "tool-1",
                "name": "read",
                "input": {"path": "README.md"},
                "output": "stale output",
                "status": "in_progress",
            },
        ),
    )
    end = projector.project(
        AcpEvent(
            type="tool_end",
            chat_id="chat-1",
            session_id="sess-1",
            payload={
                "id": "tool-1",
                "name": "read",
                "output": "fresh output",
                "status": "completed",
            },
        ),
    )

    tool_result = end[0][0].content[0]
    assert tool_result["output"] == "fresh output"
    assert tool_result["name"] == "read"


def test_projector_defers_empty_tool_start_until_end_has_input() -> None:
    projector = ACPEventProjector(harness="opencode")

    start = projector.project(
        AcpEvent(
            type="tool_start",
            chat_id="chat-1",
            session_id="sess-1",
            payload={
                "id": "tool-1",
                "name": "read",
                "input": {},
            },
        ),
    )
    end = projector.project(
        AcpEvent(
            type="tool_end",
            chat_id="chat-1",
            session_id="sess-1",
            payload={
                "id": "tool-1",
                "name": "README.md",
                "input": {"path": "/tmp/demo/README.md"},
                "output": "final content",
                "status": "completed",
            },
        ),
    )

    assert not start
    assert len(end) == 2
    assert end[0][0].content[0]["type"] == "tool_use"
    assert end[0][0].content[0]["name"] == "read"
    assert end[0][0].content[0]["input"] == {
        "path": "/tmp/demo/README.md",
    }
    assert end[1][0].content[0]["type"] == "tool_result"
    assert end[1][0].content[0]["name"] == "read"
    assert end[1][0].content[0]["output"] == "final content"


def test_projector_rotates_assistant_message_id_after_tool_boundary() -> None:
    projector = ACPEventProjector(harness="opencode")

    first = projector.project(
        AcpEvent(
            type="assistant_chunk",
            chat_id="chat-1",
            session_id="sess-1",
            payload={"text": "当前代码量"},
        ),
    )
    boundary = projector.project(
        AcpEvent(
            type="tool_start",
            chat_id="chat-1",
            session_id="sess-1",
            payload={
                "id": "tool-1",
                "name": "bash",
                "input": {"command": "rg --files"},
            },
        ),
    )
    second = projector.project(
        AcpEvent(
            type="assistant_chunk",
            chat_id="chat-1",
            session_id="sess-1",
            payload={"text": "继续统计"},
        ),
    )

    first_id = first[0][0].id
    flushed_id = boundary[0][0].id
    second_id = second[0][0].id

    assert first_id == flushed_id
    assert second_id != first_id


def test_projector_still_flushes_text_at_hidden_tool_boundary() -> None:
    projector = ACPEventProjector(
        harness="opencode",
        show_tool_calls=False,
    )

    first = projector.project(
        AcpEvent(
            type="assistant_chunk",
            chat_id="chat-1",
            session_id="sess-1",
            payload={"text": "当前代码量"},
        ),
    )
    boundary = projector.project(
        AcpEvent(
            type="tool_start",
            chat_id="chat-1",
            session_id="sess-1",
            payload={
                "id": "tool-1",
                "name": "bash",
                "input": {"command": "rg --files"},
            },
        ),
    )
    second = projector.project(
        AcpEvent(
            type="assistant_chunk",
            chat_id="chat-1",
            session_id="sess-1",
            payload={"text": "继续统计"},
        ),
    )

    first_id = first[0][0].id
    flushed_id = boundary[0][0].id
    second_id = second[0][0].id

    assert len(boundary) == 1
    assert boundary[0][1] is True
    assert boundary[0][0].content[0]["text"] == "当前代码量"
    assert first_id == flushed_id
    assert second_id != first_id
