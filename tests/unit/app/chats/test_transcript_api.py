# -*- coding: utf-8 -*-
"""API tests for durable transcript reads and cursor pagination."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from agentscope.message import Msg
from agentscope.state import AgentState
from fastapi import BackgroundTasks, HTTPException

from qwenpaw.app.chats.api import (
    _delete_chat_data,
    delete_chat,
    get_chat,
    get_chat_messages,
)
from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.app.chats.session import SafeJSONSession
from qwenpaw.app.chats.transcript import TranscriptStore
from qwenpaw.app.chats.transcript_catalog import TranscriptCatalog
from qwenpaw.schemas import Message, Role, RunStatus, TextContent
from qwenpaw.token_usage.turn_usage import TURN_USAGE_META_KEY


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
    store = TranscriptStore(tmp_path / "session.db")
    _append_turn(store, 1, "durable")
    session = SimpleNamespace(get_session_state_dict=AsyncMock())

    history = await get_chat(
        chat_id="chat-1",
        background_tasks=BackgroundTasks(),
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
    assert history.history.has_more is False
    session.get_session_state_dict.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_chat_restores_durable_turn_usage(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path / "session.db")
    store.start_turn(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        turn_id="turn-1",
    )
    store.upsert_message(
        session_id="session-1",
        turn_id="turn-1",
        message=Message(
            id="assistant-1",
            role=Role.ASSISTANT,
            content=[TextContent(text="answer")],
        ).completed(),
        ordinal=0,
    )
    store.finish_turn(
        session_id="session-1",
        turn_id="turn-1",
        status="completed",
    )
    usage = {
        "provider_id": "dashscope",
        "model_name": "qwen3.8-max",
        "total_tokens": 461440,
        "cache_hit_rate": 87.2869,
    }
    context_usage = {
        "estimated_tokens": 14467,
        "max_input_length": 1000000,
        "context_usage_ratio": 1.4467,
    }
    store.attach_turn_usage(
        session_id="session-1",
        turn_id="turn-1",
        usage=usage,
        context_usage=context_usage,
    )

    history = await get_chat(
        chat_id="chat-1",
        background_tasks=BackgroundTasks(),
        include_app_owned=True,
        mgr=SimpleNamespace(get_chat=AsyncMock(return_value=_chat())),
        session=SimpleNamespace(get_session_state_dict=AsyncMock()),
        workspace=_workspace(store),
    )

    assert history.messages[0].metadata[TURN_USAGE_META_KEY] == {
        "usage": usage,
        "context_usage": context_usage,
    }
    store.close()


@pytest.mark.asyncio
async def test_message_pages_use_opaque_item_cursor(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path / "session.db")
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
    assert newest.next_before == "2:0"
    assert newest.has_more is True
    assert [item.content[0].text for item in older.messages] == ["turn 1"]
    assert older.next_before is None
    assert older.has_more is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cursor",
    ("turn:2", "1:2:3", "2", "0:0", "2:-1"),
)
async def test_message_page_rejects_invalid_cursor(cursor: str) -> None:
    with pytest.raises(HTTPException) as raised:
        await get_chat_messages(
            chat_id="chat-1",
            before=cursor,
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
        background_tasks=BackgroundTasks(),
        include_app_owned=True,
        mgr=SimpleNamespace(get_chat=AsyncMock(return_value=_chat())),
        session=session,
        workspace=_workspace(None),
    )

    assert history.messages[0].content[0].text == "fallback"
    assert history.history is not None
    assert history.history.has_more is False


@pytest.mark.asyncio
async def test_get_chat_migrates_legacy_history_after_response(
    tmp_path: Path,
) -> None:
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
    store = TranscriptCatalog(tmp_path)
    tasks = BackgroundTasks()

    history = await get_chat(
        chat_id="chat-1",
        background_tasks=tasks,
        include_app_owned=True,
        mgr=SimpleNamespace(get_chat=AsyncMock(return_value=_chat())),
        session=session,
        workspace=_workspace(store),
    )

    assert history.messages[0].content[0].text == "fallback"
    assert (
        store.get_page(
            session_id="session-1",
            user_id="user-1",
            channel="console",
        )
        is None
    )

    await tasks()

    page = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )
    assert page is not None
    assert page.messages[0].content[0].text == "fallback"
    store.close()


@pytest.mark.asyncio
async def test_delete_chat_data_removes_all_persistence(
    tmp_path: Path,
) -> None:
    store = TranscriptCatalog(tmp_path)
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
    store.close()


@pytest.mark.asyncio
async def test_delete_keeps_data_while_another_chat_maps_same_session() -> (
    None
):
    first = _chat()
    second = first.model_copy(update={"id": "chat-2"})
    store = Mock(spec=TranscriptCatalog)
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
