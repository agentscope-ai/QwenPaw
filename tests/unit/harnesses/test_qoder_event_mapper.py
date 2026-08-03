# -*- coding: utf-8 -*-
"""Tests for translating Qoder SDK messages."""

from __future__ import annotations

from qoder_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    SessionMessage,
    StreamEvent,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from qwenpaw.harnesses.events import (
    HarnessEventKind,
    HarnessHistoryKind,
)
from qwenpaw.harnesses.qoder.event_mapper import (
    QoderEventMapper,
    history_items,
)


def test_maps_incremental_text_and_reasoning_without_duplicates() -> None:
    mapper = QoderEventMapper()
    messages = [
        StreamEvent(
            uuid="stream-1",
            session_id="session-1",
            event={
                "type": "content_block_delta",
                "delta": {"type": "thinking_delta", "thinking": "Check"},
            },
        ),
        StreamEvent(
            uuid="stream-2",
            session_id="session-1",
            event={
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "Done"},
            },
        ),
        AssistantMessage(
            content=[
                ThinkingBlock(thinking="Check", signature="signature"),
                TextBlock(text="Done"),
            ],
            model="qoder-test",
        ),
    ]

    events = [
        event for message in messages for event in mapper.convert(message)
    ]

    assert [(event.kind, event.text) for event in events] == [
        (HarnessEventKind.REASONING_DELTA, "Check"),
        (HarnessEventKind.TEXT_DELTA, "Done"),
    ]


def test_maps_tool_start_progress_and_completion() -> None:
    mapper = QoderEventMapper()
    started = mapper.convert(
        AssistantMessage(
            content=[
                ToolUseBlock(
                    id="tool-1",
                    name="Bash",
                    input={"command": "pwd"},
                ),
            ],
            model="qoder-test",
        ),
    )
    completed = mapper.convert(
        UserMessage(
            content=[
                ToolResultBlock(
                    tool_use_id="tool-1",
                    content="workspace",
                ),
            ],
        ),
    )

    assert started[0].kind == HarnessEventKind.TOOL_STARTED
    assert started[0].data["arguments"] == {"command": "pwd"}
    assert completed[0].kind == HarnessEventKind.TOOL_COMPLETED
    assert completed[0].tool_name == "Bash"
    assert completed[0].text == "workspace"


def test_maps_terminal_results() -> None:
    mapper = QoderEventMapper()

    completed = mapper.convert(
        ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="session-1",
        ),
    )
    failed = mapper.convert(
        ResultMessage(
            subtype="error",
            duration_ms=1,
            duration_api_ms=1,
            is_error=True,
            num_turns=1,
            session_id="session-1",
            errors=["Authentication failed"],
        ),
    )

    assert completed[0].kind == HarnessEventKind.COMPLETED
    assert failed[0].kind == HarnessEventKind.ERROR
    assert failed[0].text == "Authentication failed"


def test_converts_official_session_transcript_messages() -> None:
    messages = [
        SessionMessage(
            type="user",
            uuid="user-1",
            session_id="session-1",
            message={"content": "Fix the test"},
        ),
        SessionMessage(
            type="assistant",
            uuid="assistant-1",
            session_id="session-1",
            message={
                "content": [
                    {"type": "thinking", "thinking": "Inspecting"},
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "Read",
                        "input": {"path": "test.py"},
                    },
                    {"type": "text", "text": "Fixed"},
                ],
            },
        ),
    ]

    history = [item for message in messages for item in history_items(message)]

    assert [item.kind for item in history] == [
        HarnessHistoryKind.USER,
        HarnessHistoryKind.REASONING,
        HarnessHistoryKind.TOOL_CALL,
        HarnessHistoryKind.MESSAGE,
    ]
    assert history[2].data["arguments"] == {"path": "test.py"}
