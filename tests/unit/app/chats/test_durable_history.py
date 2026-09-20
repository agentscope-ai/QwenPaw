# -*- coding: utf-8 -*-
"""Durable chat-history reconstruction and API fallback tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentscope.message import Msg
from agentscope.state import AgentState

from qwenpaw.agents.context.scroll.history import HistoryStore
from qwenpaw.agents.context.scroll.serialize import msg_to_entries
from qwenpaw.app.chats.api import get_chat
from qwenpaw.app.chats.durable_history import read_durable_session
from qwenpaw.app.chats.models import ChatSpec


def _persist_message(
    store: HistoryStore,
    session_id: str,
    message: Msg,
) -> None:
    for index, entry in enumerate(msg_to_entries(message)):
        dedup_key = (
            entry.tool_call_id if entry.kind == "tool_result" else message.id
        )
        store.append(
            session_id=session_id,
            entry=entry,
            dedup_key=dedup_key or f"{message.id}-{index}",
        )


def _workspace(tmp_path):
    scroll_config = SimpleNamespace(db_filename="history.db")
    light_context = SimpleNamespace(scroll_config=scroll_config)
    running = SimpleNamespace(light_context_config=light_context)
    return SimpleNamespace(
        workspace_dir=tmp_path,
        config=SimpleNamespace(backend="qwenpaw", running=running),
        task_tracker=SimpleNamespace(
            get_status=AsyncMock(return_value="idle"),
        ),
    )


def test_read_durable_session_restores_tool_result_order(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    message = Msg(
        name="assistant",
        role="assistant",
        content=[
            {"type": "text", "text": "before"},
            {
                "type": "tool_call",
                "id": "call-1",
                "name": "lookup",
                "input": '{"query": "value"}',
            },
            {
                "type": "tool_result",
                "id": "call-1",
                "name": "lookup",
                "output": "result",
            },
            {"type": "text", "text": "after"},
        ],
    )
    _persist_message(store, "session-1", message)
    _persist_message(
        store,
        "other-session",
        Msg(
            name="user",
            role="user",
            content=[{"type": "text", "text": "other"}],
        ),
    )
    store.close()

    [restored] = read_durable_session(
        tmp_path / "history.db",
        "session-1",
    )

    assert [block.type for block in restored.content] == [
        "text",
        "tool_call",
        "tool_result",
        "text",
    ]
    assert restored.content[2].output == "result"


def test_read_durable_session_does_not_create_missing_database(tmp_path):
    db_path = tmp_path / "history.db"

    assert not read_durable_session(db_path, "session-1")
    assert not db_path.exists()


@pytest.mark.asyncio
async def test_get_chat_prefers_durable_history(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    _persist_message(
        store,
        "session-1",
        Msg(
            name="user",
            role="user",
            content=[{"type": "text", "text": "durable"}],
        ),
    )
    store.close()
    chat = ChatSpec(
        id="chat-1",
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )
    session = SimpleNamespace(get_session_state_dict=AsyncMock())

    history = await get_chat(
        chat_id=chat.id,
        include_app_owned=True,
        mgr=SimpleNamespace(get_chat=AsyncMock(return_value=chat)),
        session=session,
        workspace=_workspace(tmp_path),
    )

    assert history.messages[0].content[0].text == "durable"
    session.get_session_state_dict.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_chat_falls_back_when_durable_history_is_unreadable(
    tmp_path,
):
    (tmp_path / "history.db").write_bytes(b"not a sqlite database")
    fallback = Msg(
        name="user",
        role="user",
        content=[{"type": "text", "text": "fallback"}],
    )
    agent_state = AgentState(context=[fallback])
    session = SimpleNamespace(
        get_session_state_dict=AsyncMock(
            return_value={
                "agent": {
                    "state": agent_state.model_dump(mode="json"),
                },
            },
        ),
    )
    chat = ChatSpec(
        id="chat-1",
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )

    history = await get_chat(
        chat_id=chat.id,
        include_app_owned=True,
        mgr=SimpleNamespace(get_chat=AsyncMock(return_value=chat)),
        session=session,
        workspace=_workspace(tmp_path),
    )

    assert history.messages[0].content[0].text == "fallback"
    session.get_session_state_dict.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_chat_falls_back_when_session_has_no_durable_rows(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    _persist_message(
        store,
        "other-session",
        Msg(
            name="user",
            role="user",
            content=[{"type": "text", "text": "other"}],
        ),
    )
    store.close()
    fallback = Msg(
        name="user",
        role="user",
        content=[{"type": "text", "text": "fallback"}],
    )
    agent_state = AgentState(context=[fallback])
    session = SimpleNamespace(
        get_session_state_dict=AsyncMock(
            return_value={
                "agent": {
                    "state": agent_state.model_dump(mode="json"),
                },
            },
        ),
    )
    chat = ChatSpec(
        id="chat-1",
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )

    history = await get_chat(
        chat_id=chat.id,
        include_app_owned=True,
        mgr=SimpleNamespace(get_chat=AsyncMock(return_value=chat)),
        session=session,
        workspace=_workspace(tmp_path),
    )

    assert history.messages[0].content[0].text == "fallback"
    session.get_session_state_dict.assert_awaited_once()
