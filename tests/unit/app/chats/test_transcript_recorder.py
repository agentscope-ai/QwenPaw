# -*- coding: utf-8 -*-
"""Tests for best-effort durable transcript recording."""

from __future__ import annotations

import asyncio
import gc
import threading
import weakref
from pathlib import Path
from unittest.mock import Mock

import pytest

from qwenpaw.app.chats.transcript import TranscriptStore
from qwenpaw.app.chats.transcript_catalog import TranscriptCatalog
from qwenpaw.app.chats.transcript_recorder import (
    TRANSCRIPT_TURN_ID_CONTEXT_KEY,
    TranscriptRecorder,
)
from qwenpaw.constant import QWENPAW_CLIENT_MESSAGE_ID_KEY
from qwenpaw.runtime.console_turn_state import REGENERATE_FROM
from qwenpaw.schemas import (
    AgentRequest,
    AgentResponse,
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
    assert request.request_context is not None
    assert (
        request.request_context[TRANSCRIPT_TURN_ID_CONTEXT_KEY]
        == "client:client-1"
    )


@pytest.mark.asyncio
async def test_migrates_legacy_history_before_current_turn(
    tmp_path: Path,
) -> None:
    store = TranscriptCatalog(tmp_path)
    legacy = [
        Message(
            id="legacy-user",
            role=Role.USER,
            content=[TextContent(text="old question")],
        ).completed(),
        Message(
            id="legacy-assistant",
            role=Role.ASSISTANT,
            content=[TextContent(text="old answer")],
        ).completed(),
    ]
    recorder = TranscriptRecorder(
        store=store,
        request=_request(),
        legacy_messages=legacy,
    )

    await recorder.start()
    await recorder.observe(
        AgentResponse(
            output=[
                Message(
                    id="assistant-message",
                    role=Role.ASSISTANT,
                    content=[TextContent(text="new answer")],
                ).completed(),
            ],
            status=RunStatus.Completed,
        ),
    )

    page = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )
    assert page is not None
    assert [message.id for message in page.messages] == [
        "legacy-user",
        "legacy-assistant",
        "user-message",
        "assistant-message",
    ]
    assert store.find_turn_for_message(
        session_id="session-1",
        message_id="legacy-user",
    ) == store.find_turn_for_message(
        session_id="session-1",
        message_id="legacy-assistant",
    )
    store.close()


@pytest.mark.asyncio
async def test_cancel_preserves_in_progress_reasoning_content(
    tmp_path: Path,
) -> None:
    store = TranscriptStore(tmp_path / "session.db")
    recorder = TranscriptRecorder(
        store=store,
        request=_request(),
    )
    reasoning = Message(
        id="reasoning-message",
        type=MessageType.REASONING,
        role=Role.ASSISTANT,
        content=[],
        status=RunStatus.InProgress,
    )
    materialized = reasoning.model_copy(
        update={
            "content": [TextContent(text="partial reasoning before stop")],
            "status": RunStatus.Cancelled,
        },
    )

    await recorder.start()
    await recorder.observe(reasoning)
    await recorder.observe(materialized)
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
async def test_records_only_materialized_message_snapshots() -> None:
    store = Mock(spec=TranscriptStore)
    recorder = TranscriptRecorder(
        store=store,
        request=_request(),
    )
    message = Message(
        id="assistant-message",
        role=Role.ASSISTANT,
        content=[],
        status=RunStatus.InProgress,
    )

    await recorder.start()
    await recorder.observe(message)
    await recorder.observe(
        message.model_copy(update={"status": RunStatus.Completed}),
    )
    await recorder.observe(
        TextContent(
            text="partial",
            delta=True,
            index=0,
            msg_id=message.id,
        ),
    )
    request_writes = store.upsert_message.call_count
    assert request_writes == 1

    materialized = message.model_copy(
        update={
            "content": [TextContent(text="partial")],
            "status": RunStatus.Cancelled,
        },
    )
    await recorder.observe(materialized)

    assert store.upsert_message.call_count == request_writes + 1
    assert store.upsert_message.call_args.kwargs["message"] is materialized
    assert not hasattr(recorder, "_snapshots")
    message_ref = weakref.ref(materialized)
    store.reset_mock()
    del materialized
    gc.collect()
    assert message_ref() is None


@pytest.mark.asyncio
async def test_write_failure_degrades_without_raising() -> None:
    store = Mock(spec=TranscriptStore)
    store.start_turn.side_effect = OSError("disk full")
    recorder = TranscriptRecorder(
        store=store,
        request=_request(),
    )

    await recorder.start()
    await recorder.observe(
        Message(role=Role.ASSISTANT, content=[TextContent(text="reply")]),
    )

    store.upsert_message.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_preserves_cancelled_error_when_write_fails() -> None:
    entered = threading.Event()
    release = threading.Event()
    store = Mock(spec=TranscriptStore)

    def fail_start(**_kwargs: object) -> None:
        entered.set()
        assert release.wait(timeout=2)
        raise OSError("disk unavailable")

    store.start_turn.side_effect = fail_start
    recorder = TranscriptRecorder(store=store, request=_request())
    task = asyncio.create_task(recorder.start())
    assert await asyncio.to_thread(entered.wait, 2)

    task.cancel()
    release.set()

    with pytest.raises(asyncio.CancelledError):
        await task


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

    assert request.request_context is not None
    assert request.request_context[TRANSCRIPT_TURN_ID_CONTEXT_KEY] == (
        "regenerate:client-new"
    )
    assert page is not None
    assert [message.id for message in page.messages] == expected_ids
    store.close()
