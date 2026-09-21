# -*- coding: utf-8 -*-
"""API tests for durable transcript reads and cursor pagination."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from agentscope.message import Msg
from agentscope.state import AgentState
from fastapi import HTTPException

from qwenpaw.app.chats.api import (
    _delete_chat_data,
    delete_chat,
    get_chat,
    get_chat_messages,
)
from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.app.chats.session import SafeJSONSession
from qwenpaw.app.chats.transcript import TranscriptStore
from qwenpaw.schemas import Message, MessageType, Role, RunStatus, TextContent


def _chat() -> ChatSpec:
    return ChatSpec(
        id="chat-1",
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )


def _workspace(store) -> SimpleNamespace:
    return SimpleNamespace(
        transcript_store=store,
        config=SimpleNamespace(backend="qwenpaw"),
        task_tracker=SimpleNamespace(
            get_status=AsyncMock(return_value="idle"),
        ),
    )


def _append_turn(
    store: TranscriptStore,
    number: int,
    text: str,
) -> None:
    turn_id = f"turn-{number}"
    store.start_turn(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        turn_id=turn_id,
        source="qwenpaw",
    )
    store.upsert_message(
        session_id="session-1",
        turn_id=turn_id,
        message=Message(
            id=f"message-{number}",
            role=Role.USER,
            content=[TextContent(text=text)],
            status=RunStatus.Completed,
        ),
        ordinal=0,
    )
    store.finish_turn(
        session_id="session-1",
        turn_id=turn_id,
        status="completed",
    )


@pytest.mark.asyncio
async def test_get_chat_prefers_transcript_page(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path / "transcript.db")
    _append_turn(store, 1, "durable")
    session = SimpleNamespace(get_session_state_dict=AsyncMock())

    history = await get_chat(
        chat_id="chat-1",
        include_app_owned=True,
        mgr=SimpleNamespace(get_chat=AsyncMock(return_value=_chat())),
        session=session,
        workspace=_workspace(store),
    )

    assert history.messages[0].content[0].text == "durable"
    assert history.messages[0].metadata is not None
    assert history.messages[0].metadata["timestamp"]
    assert history.messages[0].metadata["qwenpaw_turn_state"] == {
        "status": "completed",
    }
    assert history.history is not None
    assert history.history.completeness == "complete"
    assert history.history.has_more is False
    session.get_session_state_dict.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_chat_defers_running_outputs_to_sse_replay(
    tmp_path: Path,
) -> None:
    store = TranscriptStore(tmp_path / "transcript.db")
    store.start_turn(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        turn_id="turn-1",
        source="qwenpaw",
    )
    for ordinal, message in enumerate(
        [
            Message(
                id="user-1",
                role=Role.USER,
                content=[TextContent(text="question")],
                status=RunStatus.Completed,
            ),
            Message(
                id="reasoning-1",
                type=MessageType.REASONING,
                role=Role.ASSISTANT,
                content=[],
                status=RunStatus.InProgress,
            ),
        ],
    ):
        store.upsert_message(
            session_id="session-1",
            turn_id="turn-1",
            message=message,
            ordinal=ordinal,
        )
    workspace = _workspace(store)
    workspace.task_tracker.get_status.return_value = "running"

    history = await get_chat(
        chat_id="chat-1",
        include_app_owned=True,
        mgr=SimpleNamespace(get_chat=AsyncMock(return_value=_chat())),
        session=SimpleNamespace(get_session_state_dict=AsyncMock()),
        workspace=workspace,
    )

    assert history.status == "running"
    assert [message.id for message in history.messages] == ["user-1"]
    store.close()


@pytest.mark.asyncio
async def test_message_pages_use_opaque_turn_cursor(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path / "transcript.db")
    for number in range(1, 4):
        _append_turn(store, number, f"turn {number}")
    manager = SimpleNamespace(get_chat=AsyncMock(return_value=_chat()))
    workspace = _workspace(store)

    newest = await get_chat_messages(
        chat_id="chat-1",
        before=None,
        limit=2,
        mgr=manager,
        workspace=workspace,
    )
    older = await get_chat_messages(
        chat_id="chat-1",
        before=newest.next_before,
        limit=2,
        mgr=manager,
        workspace=workspace,
    )

    assert [item.content[0].text for item in newest.messages] == [
        "turn 2",
        "turn 3",
    ]
    assert newest.next_before == "v1:2"
    assert newest.has_more is True
    assert [item.content[0].text for item in older.messages] == ["turn 1"]
    assert older.next_before is None
    assert older.has_more is False


@pytest.mark.asyncio
async def test_message_page_rejects_invalid_cursor() -> None:
    with pytest.raises(HTTPException) as raised:
        await get_chat_messages(
            chat_id="chat-1",
            before="turn:2",
            limit=50,
            mgr=SimpleNamespace(get_chat=AsyncMock(return_value=_chat())),
            workspace=_workspace(None),
        )

    assert raised.value.status_code == 400


@pytest.mark.asyncio
async def test_get_chat_falls_back_without_transcript() -> None:
    fallback = Msg(
        name="user",
        role="user",
        content=[{"type": "text", "text": "fallback"}],
    )
    state = AgentState(context=[fallback]).model_dump(mode="json")
    session = SimpleNamespace(
        get_session_state_dict=AsyncMock(
            return_value={"agent": {"state": state}},
        ),
    )

    history = await get_chat(
        chat_id="chat-1",
        include_app_owned=True,
        mgr=SimpleNamespace(get_chat=AsyncMock(return_value=_chat())),
        session=session,
        workspace=_workspace(None),
    )

    assert history.messages[0].content[0].text == "fallback"
    assert history.history is not None
    assert history.history.completeness == "partial"


@pytest.mark.asyncio
async def test_get_chat_falls_back_when_transcript_read_fails() -> None:
    store = Mock(spec=TranscriptStore)
    store.get_page.side_effect = OSError("unavailable")
    session = SimpleNamespace(
        get_session_state_dict=AsyncMock(return_value={}),
    )

    history = await get_chat(
        chat_id="chat-1",
        include_app_owned=True,
        mgr=SimpleNamespace(get_chat=AsyncMock(return_value=_chat())),
        session=session,
        workspace=_workspace(store),
    )

    assert history.messages == []
    assert history.history is not None
    assert history.history.completeness == "partial"


@pytest.mark.asyncio
async def test_get_chat_hydrates_external_history_into_transcript(
    tmp_path: Path,
) -> None:
    store = TranscriptStore(tmp_path / "transcript.db")

    async def hydrate_session(**_kwargs) -> None:
        store.import_history_if_missing(
            session_id="session-1",
            user_id="user-1",
            channel="console",
            source="harness_import",
            turns=[
                (
                    "provider-turn",
                    [
                        Message(
                            id="provider-message",
                            role=Role.USER,
                            content=[TextContent(text="restored")],
                        ).completed(),
                    ],
                ),
            ],
        )

    hydrate = AsyncMock(side_effect=hydrate_session)
    session = SimpleNamespace(
        get_session_state_dict=AsyncMock(
            return_value={"agent": {"state": {"context": ["legacy"]}}},
        ),
    )
    workspace = SimpleNamespace(
        transcript_store=store,
        config=SimpleNamespace(backend="codex", backend_settings={}),
        task_tracker=SimpleNamespace(
            get_status=AsyncMock(return_value="idle"),
        ),
        harness_runtime=SimpleNamespace(hydrate_session=hydrate),
    )

    history = await get_chat(
        chat_id="chat-1",
        include_app_owned=True,
        mgr=SimpleNamespace(get_chat=AsyncMock(return_value=_chat())),
        session=session,
        workspace=workspace,
    )

    assert [message.id for message in history.messages] == [
        "provider-message",
    ]
    assert history.history is not None
    assert history.history.completeness == "partial"
    hydrate.assert_awaited_once()
    session.get_session_state_dict.assert_not_awaited()
    store.close()


@pytest.mark.asyncio
async def test_delete_chat_data_removes_all_persistence(
    tmp_path: Path,
) -> None:
    store = TranscriptStore(tmp_path / "transcript.db")
    _append_turn(store, 1, "durable")
    session = SafeJSONSession(save_dir=str(tmp_path / "sessions"))
    await session.update_session_state(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        key="agent.value",
        value=1,
    )
    checkpoint_delete = AsyncMock()
    workspace = SimpleNamespace(
        transcript_store=store,
        session=session,
    )

    with patch(
        "qwenpaw.app.chats.api.CHECKPOINT_RUNTIME."
        "delete_session_checkpoints",
        checkpoint_delete,
    ):
        await _delete_chat_data(workspace, [_chat()])

    assert (
        store.get_page(
            session_id="session-1",
            user_id="user-1",
            channel="console",
        )
        is None
    )
    assert (
        await session.get_session_state_dict(
            "session-1",
            "user-1",
            "console",
        )
        == {}
    )
    checkpoint_delete.assert_awaited_once_with(
        workspace,
        [("session-1", "user-1", "console")],
    )


@pytest.mark.asyncio
async def test_delete_failure_keeps_chat_metadata_for_retry() -> None:
    store = Mock(spec=TranscriptStore)
    store.delete_session.side_effect = sqlite3.OperationalError("locked")
    manager = SimpleNamespace(
        get_chat=AsyncMock(return_value=_chat()),
        list_chats=AsyncMock(return_value=[_chat()]),
        delete_chats=AsyncMock(return_value=True),
    )
    workspace = SimpleNamespace(transcript_store=store, session=None)

    with pytest.raises(HTTPException) as exc_info:
        await delete_chat(
            chat_id="chat-1",
            mgr=manager,
            workspace=workspace,
        )

    assert exc_info.value.status_code == 500
    manager.delete_chats.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_keeps_data_while_another_chat_maps_same_session() -> (
    None
):
    first = _chat()
    second = first.model_copy(update={"id": "chat-2"})
    store = Mock(spec=TranscriptStore)
    manager = SimpleNamespace(
        get_chat=AsyncMock(return_value=first),
        list_chats=AsyncMock(return_value=[first, second]),
        delete_chats=AsyncMock(return_value=True),
    )
    workspace = SimpleNamespace(transcript_store=store, session=None)

    result = await delete_chat(
        chat_id=first.id,
        mgr=manager,
        workspace=workspace,
    )

    assert result == {"deleted": True}
    store.delete_session.assert_not_called()
    manager.delete_chats.assert_awaited_once_with(chat_ids=[first.id])
