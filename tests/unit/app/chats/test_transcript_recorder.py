# -*- coding: utf-8 -*-
"""Tests for best-effort durable transcript recording."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from unittest.mock import Mock

import pytest

from qwenpaw.app.chats.transcript import TranscriptStore
from qwenpaw.app.chats.transcript_recorder import (
    TRANSCRIPT_TURN_ID_CONTEXT_KEY,
    TranscriptRecorder,
)
from qwenpaw.constant import QWENPAW_CLIENT_MESSAGE_ID_KEY
from qwenpaw.runtime.console_turn_state import REGENERATE_FROM
from qwenpaw.schemas import (
    AgentRequest,
    AgentResponse,
    DataContent,
    Message,
    MessageType,
    Role,
    RunStatus,
    TextContent,
)


def _request() -> AgentRequest:
    return AgentRequest(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        input=[
            Message(
                id="user-message",
                role=Role.USER,
                content=[TextContent(text="hello")],
                metadata={QWENPAW_CLIENT_MESSAGE_ID_KEY: "client-1"},
            ),
        ],
    )


@pytest.mark.asyncio
async def test_records_request_and_terminal_response(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path / "session.db")
    request = _request()
    recorder = TranscriptRecorder(
        store=store,
        request=request,
        source="qwenpaw",
    )
    assistant = Message(
        id="assistant-message",
        role=Role.ASSISTANT,
        content=[TextContent(text="hi")],
        status=RunStatus.Completed,
    )

    await recorder.start()
    await recorder.observe(assistant.model_copy(update={"content": []}))
    await recorder.observe(assistant)
    await recorder.observe(
        AgentResponse(
            output=[assistant],
            status=RunStatus.Completed,
            completed_at="2026-09-20T12:00:00+00:00",
        ),
    )

    page = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )
    assert page is not None
    assert [message.id for message in page.messages] == [
        "user-message",
        "assistant-message",
    ]
    assert page.messages[-1].content[0].text == "hi"
    assert page.messages[-1].metadata is not None
    assert page.messages[-1].metadata["finished_at"] == (
        "2026-09-20T12:00:00+00:00"
    )
    row = store._conn.execute(  # pylint: disable=protected-access
        "SELECT finished_at FROM transcript_messages "
        "WHERE message_id = 'assistant-message'",
    ).fetchone()
    assert row["finished_at"] == "2026-09-20T12:00:00+00:00"
    assert recorder.turn_id == "client:client-1"
    assert request.request_context is not None
    assert (
        request.request_context[TRANSCRIPT_TURN_ID_CONTEXT_KEY]
        == recorder.turn_id
    )


@pytest.mark.asyncio
async def test_cancel_preserves_in_progress_reasoning_content(
    tmp_path: Path,
) -> None:
    store = TranscriptStore(tmp_path / "session.db")
    recorder = TranscriptRecorder(
        store=store,
        request=_request(),
        source="qwenpaw",
    )
    reasoning = Message(
        id="reasoning-message",
        type=MessageType.REASONING,
        role=Role.ASSISTANT,
        content=[],
        status=RunStatus.InProgress,
    )
    chunk = TextContent(
        text="partial reasoning before stop",
        delta=True,
        index=0,
        status=RunStatus.InProgress,
        msg_id=reasoning.id,
    )

    await recorder.start()
    await recorder.observe(reasoning)
    await recorder.observe(chunk)
    await recorder.observe(
        reasoning.model_copy(
            update={"content": [], "status": RunStatus.Completed},
        ),
    )
    await recorder.observe(
        AgentResponse(
            output=[],
            status=RunStatus.Cancelled,
            completed_at="2026-09-21T01:22:33+00:00",
        ),
    )

    page = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )

    assert page is not None
    saved = page.messages[-1]
    assert saved.id == reasoning.id
    assert saved.content[0].text == "partial reasoning before stop"
    assert saved.status == RunStatus.Completed
    assert saved.metadata is not None
    assert saved.metadata["finished_at"] == "2026-09-21T01:22:33+00:00"
    store.close()


@pytest.mark.asyncio
async def test_preserves_interleaved_parallel_tool_event_order(
    tmp_path: Path,
) -> None:
    store = TranscriptStore(tmp_path / "session.db")
    recorder = TranscriptRecorder(
        store=store,
        request=_request(),
        source="qwenpaw",
    )
    tool_messages = [
        Message(
            id=message_id,
            type=message_type,
            role=role,
            content=[DataContent(data={"call_id": call_id})],
        ).completed()
        for message_id, message_type, role, call_id in (
            ("call-1", MessageType.PLUGIN_CALL, Role.ASSISTANT, "tool-1"),
            ("call-2", MessageType.PLUGIN_CALL, Role.ASSISTANT, "tool-2"),
            ("output-2", MessageType.PLUGIN_CALL_OUTPUT, Role.TOOL, "tool-2"),
            ("output-1", MessageType.PLUGIN_CALL_OUTPUT, Role.TOOL, "tool-1"),
        )
    ]

    await recorder.start()
    await recorder.observe(
        AgentResponse(output=tool_messages, status=RunStatus.Completed),
    )
    page = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )

    assert page is not None
    assert [message.id for message in page.messages] == [
        "user-message",
        "call-1",
        "call-2",
        "output-2",
        "output-1",
    ]
    store.close()


@pytest.mark.asyncio
async def test_records_failed_terminal_code_without_error_detail(
    tmp_path: Path,
) -> None:
    store = TranscriptStore(tmp_path / "session.db")
    recorder = TranscriptRecorder(
        store=store,
        request=_request(),
        source="qwenpaw",
    )
    await recorder.start()
    await recorder.observe(
        AgentResponse(
            status=RunStatus.Failed,
            error={"code": "bad", "message": "safe message"},
        ),
    )

    row = store._conn.execute(  # pylint: disable=protected-access
        "SELECT status, error_json FROM transcript_turns",
    ).fetchone()
    assert tuple(row) == (
        "failed",
        '{"code": "bad", "message": ""}',
    )


@pytest.mark.asyncio
async def test_write_failure_degrades_without_raising() -> None:
    store = Mock(spec=TranscriptStore)
    store.start_turn.side_effect = OSError("disk full")
    recorder = TranscriptRecorder(
        store=store,
        request=_request(),
        source="qwenpaw",
    )

    await recorder.start()
    await recorder.observe(
        Message(role=Role.ASSISTANT, content=[TextContent(text="reply")]),
    )

    assert recorder.degraded is True
    store.upsert_message.assert_not_called()


@pytest.mark.asyncio
async def test_none_store_is_a_noop() -> None:
    recorder = TranscriptRecorder(
        store=None,
        request=_request(),
        source="qwenpaw",
    )

    await recorder.start()
    await recorder.finish("cancelled")

    assert recorder.degraded is False


@pytest.mark.asyncio
async def test_cancelled_start_can_still_finish_the_created_turn() -> None:
    entered = threading.Event()
    release = threading.Event()
    store = Mock(spec=TranscriptStore)

    def start_turn(**_kwargs) -> int:
        entered.set()
        release.wait(timeout=2)
        return 1

    store.start_turn.side_effect = start_turn
    recorder = TranscriptRecorder(
        store=store,
        request=_request(),
        source="qwenpaw",
    )
    task = asyncio.create_task(recorder.start())
    await asyncio.to_thread(entered.wait, 2)

    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    await recorder.finish("cancelled")

    store.finish_turn.assert_called_once_with(
        session_id="session-1",
        turn_id="client:client-1",
        status="cancelled",
        error=None,
        finished_at=None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected_ids"),
    [
        (
            RunStatus.Completed,
            ["user-replacement", "assistant-replacement"],
        ),
        (
            RunStatus.Failed,
            ["user-original", "assistant-original", "user-replacement"],
        ),
    ],
)
async def test_regeneration_replaces_original_only_after_success(
    tmp_path: Path,
    status: RunStatus,
    expected_ids: list[str],
) -> None:
    store = TranscriptStore(tmp_path / "session.db")
    store.start_turn(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        turn_id="original",
        source="qwenpaw",
    )
    original_messages = [
        Message(
            id="user-original",
            role=Role.USER,
            content=[TextContent(text="question")],
            metadata={QWENPAW_CLIENT_MESSAGE_ID_KEY: "client-original"},
        ).completed(),
        Message(
            id="assistant-original",
            role=Role.ASSISTANT,
            content=[TextContent(text="old")],
        ).completed(),
    ]
    for ordinal, message in enumerate(original_messages):
        store.upsert_message(
            session_id="session-1",
            turn_id="original",
            message=message,
            ordinal=ordinal,
        )
    store.finish_turn(
        session_id="session-1",
        turn_id="original",
        status="completed",
    )
    request = AgentRequest(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        request_context={REGENERATE_FROM: "client-original"},
        input=[
            Message(
                id="user-replacement",
                role=Role.USER,
                content=[TextContent(text="question")],
                metadata={QWENPAW_CLIENT_MESSAGE_ID_KEY: "client-new"},
            ),
        ],
    )
    recorder = TranscriptRecorder(
        store=store,
        request=request,
        source="qwenpaw",
    )
    assistant = Message(
        id="assistant-replacement",
        role=Role.ASSISTANT,
        content=[TextContent(text="new")],
    ).completed()

    await recorder.start()
    if status == RunStatus.Completed:
        await recorder.observe(assistant)
    await recorder.observe(AgentResponse(status=status))
    page = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )

    assert recorder.turn_id == "regenerate:client-new"
    assert page is not None
    assert [message.id for message in page.messages] == expected_ids
    store.close()
