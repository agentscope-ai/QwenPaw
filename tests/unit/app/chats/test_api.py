# -*- coding: utf-8 -*-
"""Ownership-boundary tests for the global chat API."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentscope.message import Msg
from agentscope.state import AgentState
from fastapi import HTTPException

from qwenpaw.agents.context.scroll.history import HistoryStore
from qwenpaw.agents.context.scroll.serialize import msg_to_entries
from qwenpaw.app.chats.api import get_chat, list_chats
from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.constant import (
    QWENPAW_MESSAGE_TAG_KEY,
    SCROLL_MEMORY_MESSAGE_TAG,
)


def _chat(chat_id: str, *, app_id: str | None = None) -> ChatSpec:
    meta = (
        {
            "pawapp": {
                "app_id": app_id,
                "agent_id": "datapaw",
            },
        }
        if app_id
        else {}
    )
    return ChatSpec(
        id=chat_id,
        session_id=f"console:{chat_id}",
        user_id="default",
        channel="console",
        meta=meta,
    )


def _message(role: str, text: str, message_id: str) -> Msg:
    return Msg(
        id=message_id,
        name=role,
        role=role,
        content=[{"type": "text", "text": text}],
    )


def _workspace(
    tmp_path: Path,
    *,
    backend: str = "qwenpaw",
    strategy: str = "scroll",
):
    config = SimpleNamespace(
        backend=backend,
        running=SimpleNamespace(
            light_context_config=SimpleNamespace(
                strategy=strategy,
                scroll_config=SimpleNamespace(db_filename="history.db"),
            ),
        ),
    )
    return SimpleNamespace(
        agent_id="default",
        config=config,
        workspace_dir=tmp_path,
        task_tracker=SimpleNamespace(
            get_status=AsyncMock(return_value="idle"),
        ),
    )


def _persist_messages(
    db_path: Path,
    session_id: str,
    messages: list[Msg],
) -> None:
    store = HistoryStore(db_path)
    try:
        for message in messages:
            entries = msg_to_entries(message)
            assert len(entries) == 1
            store.append(
                session_id=session_id,
                agent_id="default",
                dedup_key=message.id,
                entry=entries[0],
            )
    finally:
        store.close()


def _session_state(messages: list[Msg]) -> dict:
    state = AgentState(context=messages).model_dump(mode="json")
    return {"agent": {"state": state}}


def _message_texts(history) -> list[str]:
    return [
        "".join(
            content.text
            for content in message.content
            if getattr(content, "text", None) is not None
        )
        for message in history.messages
    ]


@pytest.mark.asyncio
async def test_list_chats_can_exclude_app_owned_dialogues():
    normal = _chat("normal")
    app_owned = _chat("app-owned", app_id="datapaw")
    manager = SimpleNamespace(
        list_chats=AsyncMock(return_value=[normal, app_owned]),
    )
    tracker = SimpleNamespace(get_status=AsyncMock(return_value="idle"))

    result = await list_chats(
        user_id=None,
        channel=None,
        archived=False,
        include_app_owned=False,
        mgr=manager,
        workspace=SimpleNamespace(task_tracker=tracker),
    )

    assert [chat.id for chat in result] == ["normal"]
    tracker.get_status.assert_awaited_once_with("normal")


@pytest.mark.asyncio
async def test_get_chat_hides_app_owned_dialogue_when_caller_opts_out():
    manager = SimpleNamespace(
        get_chat=AsyncMock(return_value=_chat("app-owned", app_id="datapaw")),
    )

    with pytest.raises(HTTPException) as raised:
        await get_chat(
            chat_id="app-owned",
            include_app_owned=False,
            mgr=manager,
            session=SimpleNamespace(),
            workspace=SimpleNamespace(),
        )

    assert raised.value.status_code == 404


@pytest.mark.asyncio
async def test_get_chat_restores_evicted_scroll_history_and_live_tail(
    tmp_path: Path,
):
    chat = _chat("normal")
    old_user = _message("user", "old question", "old-user")
    old_assistant = _message("assistant", "old answer", "old-assistant")
    current_user = _message("user", "current question", "current-user")
    persisted_reply = _message(
        "assistant",
        "partial reply",
        "current-assistant",
    )
    live_reply = _message(
        "assistant",
        "complete reply",
        "current-assistant",
    )
    _persist_messages(
        tmp_path / "history.db",
        chat.session_id,
        [old_user, old_assistant, current_user, persisted_reply],
    )
    session = SimpleNamespace(
        get_session_state_dict=AsyncMock(
            return_value=_session_state([current_user, live_reply]),
        ),
    )

    history = await get_chat(
        chat_id=chat.id,
        include_app_owned=True,
        mgr=SimpleNamespace(get_chat=AsyncMock(return_value=chat)),
        session=session,
        workspace=_workspace(tmp_path),
    )

    assert _message_texts(history) == [
        "old question",
        "old answer",
        "current question",
        "complete reply",
    ]


@pytest.mark.asyncio
async def test_get_chat_falls_back_to_live_state_without_scroll_database(
    tmp_path: Path,
):
    chat = _chat("normal")
    live_user = _message("user", "still visible", "live-user")
    session = SimpleNamespace(
        get_session_state_dict=AsyncMock(
            return_value=_session_state([live_user]),
        ),
    )

    history = await get_chat(
        chat_id=chat.id,
        include_app_owned=True,
        mgr=SimpleNamespace(get_chat=AsyncMock(return_value=chat)),
        session=session,
        workspace=_workspace(tmp_path),
    )

    assert _message_texts(history) == ["still visible"]
    assert not (tmp_path / "history.db").exists()


@pytest.mark.asyncio
async def test_get_chat_restores_without_snapshot_and_hides_scroll_placeholder(
    tmp_path: Path,
):
    chat = _chat("normal")
    old_user = _message("user", "durable question", "old-user")
    placeholder = Msg(
        id="visual-placeholder",
        name="memory",
        role="user",
        content=[{"type": "text", "text": "compressed context"}],
        metadata={
            QWENPAW_MESSAGE_TAG_KEY: SCROLL_MEMORY_MESSAGE_TAG,
        },
    )
    _persist_messages(
        tmp_path / "history.db",
        chat.session_id,
        [old_user, placeholder],
    )
    session = SimpleNamespace(
        get_session_state_dict=AsyncMock(return_value={}),
    )

    history = await get_chat(
        chat_id=chat.id,
        include_app_owned=True,
        mgr=SimpleNamespace(get_chat=AsyncMock(return_value=chat)),
        session=session,
        workspace=_workspace(tmp_path),
    )

    assert _message_texts(history) == ["durable question"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("backend", "strategy"),
    [("codex", "scroll"), ("qwenpaw", "native")],
)
async def test_get_chat_does_not_mix_inactive_scroll_history(
    tmp_path: Path,
    backend: str,
    strategy: str,
):
    chat = _chat("normal")
    hidden_old = _message("user", "stale history", "stale-user")
    live_user = _message("user", "active history", "live-user")
    _persist_messages(
        tmp_path / "history.db",
        chat.session_id,
        [hidden_old],
    )
    session = SimpleNamespace(
        get_session_state_dict=AsyncMock(
            return_value=_session_state([live_user]),
        ),
    )

    history = await get_chat(
        chat_id=chat.id,
        include_app_owned=True,
        mgr=SimpleNamespace(get_chat=AsyncMock(return_value=chat)),
        session=session,
        workspace=_workspace(
            tmp_path,
            backend=backend,
            strategy=strategy,
        ),
    )

    assert _message_texts(history) == ["active history"]
