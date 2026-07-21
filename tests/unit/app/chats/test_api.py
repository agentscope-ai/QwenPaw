# -*- coding: utf-8 -*-
"""Unit tests for destructive chat deletion across persistence layers."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from qwenpaw.agents.context.scroll.history import HistoryStore
from qwenpaw.agents.context.types import LogEntry
from qwenpaw.app.chats.api import _delete_chat_data
from qwenpaw.app.chats.manager import ChatManager
from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.app.chats.repo import JsonChatRepository
from qwenpaw.app.chats.session import SafeJSONSession


class _Tracker:
    def __init__(self, running: set[str] | None = None) -> None:
        self.running = running or set()

    async def get_status(self, chat_id: str) -> str:
        return "running" if chat_id in self.running else "idle"


def _workspace(tmp_path: Path, tracker: _Tracker | None = None):
    scroll_config = SimpleNamespace(db_filename="history.db")
    light_config = SimpleNamespace(scroll_config=scroll_config)
    running = SimpleNamespace(light_context_config=light_config)
    return SimpleNamespace(
        workspace_dir=tmp_path,
        config=SimpleNamespace(running=running),
        task_tracker=tracker or _Tracker(),
    )


async def _seed_chat(
    manager: ChatManager,
    session: SafeJSONSession,
    history: HistoryStore,
    *,
    chat_id: str,
    session_id: str,
    user_id: str,
) -> ChatSpec:
    spec = ChatSpec(
        id=chat_id,
        session_id=session_id,
        user_id=user_id,
        channel="console",
    )
    await manager.create_chat(spec)
    await session.update_session_state(
        session_id,
        "agent.value",
        chat_id,
        user_id,
        "console",
    )
    history.append(
        session_id=session_id,
        dedup_key=chat_id,
        entry=LogEntry(
            kind="model_turn",
            role="assistant",
            content=chat_id,
        ),
    )
    return spec


@pytest.mark.asyncio
async def test_delete_chat_data_removes_state_history_and_spec(tmp_path: Path):
    manager = ChatManager(repo=JsonChatRepository(tmp_path / "chats.json"))
    session = SafeJSONSession(str(tmp_path / "sessions"))
    history = HistoryStore(tmp_path / "history.db")
    deleted = await _seed_chat(
        manager,
        session,
        history,
        chat_id="delete-me",
        session_id="console:delete",
        user_id="delete",
    )
    retained = await _seed_chat(
        manager,
        session,
        history,
        chat_id="keep-me",
        session_id="console:keep",
        user_id="keep",
    )
    history.close()

    result = await _delete_chat_data(
        [deleted.id],
        mgr=manager,
        session=session,
        workspace=_workspace(tmp_path),
    )

    assert result is True
    assert await manager.get_chat(deleted.id) is None
    assert await manager.get_chat(retained.id) is not None
    deleted_file = tmp_path / "sessions/console/delete_console--delete.json"
    retained_file = tmp_path / "sessions/console/keep_console--keep.json"
    assert not deleted_file.exists()
    assert retained_file.exists()
    check = HistoryStore(tmp_path / "history.db")
    try:
        assert check.count("console:delete") == 0
        assert check.count("console:keep") == 1
    finally:
        check.close()


@pytest.mark.asyncio
async def test_delete_chat_data_preserves_shared_session(tmp_path: Path):
    manager = ChatManager(repo=JsonChatRepository(tmp_path / "chats.json"))
    session = SafeJSONSession(str(tmp_path / "sessions"))
    history = HistoryStore(tmp_path / "history.db")
    first = await _seed_chat(
        manager,
        session,
        history,
        chat_id="first",
        session_id="console:shared",
        user_id="shared",
    )
    second = ChatSpec(
        id="second",
        session_id="console:shared",
        user_id="shared",
        channel="console",
    )
    await manager.create_chat(second)
    history.close()

    await _delete_chat_data(
        [first.id],
        mgr=manager,
        session=session,
        workspace=_workspace(tmp_path),
    )

    assert await manager.get_chat(second.id) is not None
    state_file = tmp_path / "sessions/console/shared_console--shared.json"
    assert state_file.exists()
    check = HistoryStore(tmp_path / "history.db")
    try:
        assert check.count("console:shared") == 1
    finally:
        check.close()


@pytest.mark.asyncio
async def test_delete_running_chat_is_rejected(tmp_path: Path):
    manager = ChatManager(repo=JsonChatRepository(tmp_path / "chats.json"))
    session = SafeJSONSession(str(tmp_path / "sessions"))
    spec = ChatSpec(id="running", session_id="console:r", user_id="r")
    await manager.create_chat(spec)

    with pytest.raises(HTTPException) as exc_info:
        await _delete_chat_data(
            [spec.id],
            mgr=manager,
            session=session,
            workspace=_workspace(tmp_path, _Tracker({spec.id})),
        )

    assert exc_info.value.status_code == 409
    assert await manager.get_chat(spec.id) is not None
