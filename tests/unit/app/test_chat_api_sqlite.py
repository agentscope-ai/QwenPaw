# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from copaw.app.runner.api import router
from copaw.app.runner.manager import ChatManager
from copaw.app.runner.models import ChatSpec
from copaw.app.runner.repo.sqlite_repo import SQLiteChatRepository
from copaw.app.runner.session import SQLiteSession


class FakeStateModule:
    def __init__(self, state: dict):
        self._state = state

    def state_dict(self) -> dict:
        return self._state


def _build_client(
    tmp_path: Path,
) -> tuple[TestClient, ChatManager, SQLiteSession]:
    db_path = tmp_path / "state.sqlite3"
    sessions_dir = tmp_path / "sessions"
    repo = SQLiteChatRepository(db_path)
    manager = ChatManager(repo=repo)
    session = SQLiteSession(save_dir=str(sessions_dir), db_path=str(db_path))

    app = FastAPI()
    app.include_router(router)
    app.state.chat_manager = manager
    app.state.runner = SimpleNamespace(session=session)
    return TestClient(app), manager, session


def test_chat_api_list_filter_and_detail_with_sqlite_backend(
    tmp_path: Path,
) -> None:
    client, manager, session = _build_client(tmp_path)

    first = ChatSpec(
        id="chat-1",
        name="Alpha",
        session_id="console:alice",
        user_id="alice",
        channel="console",
    )
    second = ChatSpec(
        id="chat-2",
        name="Beta",
        session_id="discord:bob",
        user_id="bob",
        channel="discord",
    )

    asyncio.run(manager.create_chat(first))
    asyncio.run(manager.create_chat(second))
    asyncio.run(
        session.save_session_state(
            session_id="console:alice",
            user_id="alice",
            agent=FakeStateModule({"memory": []}),
        ),
    )

    all_chats = client.get("/chats")
    assert all_chats.status_code == 200
    assert [item["id"] for item in all_chats.json()] == ["chat-1", "chat-2"]

    filtered = client.get("/chats", params={"user_id": "alice"})
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()] == ["chat-1"]

    detail = client.get("/chats/chat-1")
    assert detail.status_code == 200
    assert detail.json() == {"messages": []}


def test_chat_api_create_update_and_delete_with_sqlite_backend(
    tmp_path: Path,
) -> None:
    client, _, _ = _build_client(tmp_path)

    created = client.post(
        "/chats",
        json={
            "id": "",
            "name": "New Chat",
            "session_id": "console:alice",
            "user_id": "alice",
            "channel": "console",
            "meta": {"tag": "x"},
        },
    )
    assert created.status_code == 200
    chat = created.json()
    assert chat["name"] == "New Chat"
    assert chat["id"]

    updated = client.put(
        f"/chats/{chat['id']}",
        json={
            **chat,
            "name": "Renamed Chat",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Renamed Chat"

    deleted = client.post("/chats/batch-delete", json=[chat["id"]])
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True}

    missing = client.get(f"/chats/{chat['id']}")
    assert missing.status_code == 404
