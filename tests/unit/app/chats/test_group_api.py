# -*- coding: utf-8 -*-
"""Tests for chat-group API routing and mutations."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.chats.api import get_chat_manager, router
from qwenpaw.app.chats.manager import ChatManager
from qwenpaw.app.chats.models import (
    DEFAULT_CHAT_GROUP_ID,
    SUBAGENT_CHAT_GROUP_ID,
)
from qwenpaw.app.chats.repo import JsonChatRepository


def _client(tmp_path: Path) -> TestClient:
    manager = ChatManager(repo=JsonChatRepository(tmp_path / "chats.json"))
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_chat_manager] = lambda: manager
    return TestClient(app)


def test_group_crud_and_order_routes(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/chats/groups")
    assert response.status_code == 200
    assert [group["id"] for group in response.json()] == [
        DEFAULT_CHAT_GROUP_ID,
        SUBAGENT_CHAT_GROUP_ID,
    ]

    response = client.post("/chats/groups", json={"name": "Work"})
    assert response.status_code == 200
    custom_group = response.json()

    response = client.put(
        f"/chats/groups/{custom_group['id']}",
        json={"name": "Projects"},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Projects"

    group_ids = [
        custom_group["id"],
        SUBAGENT_CHAT_GROUP_ID,
        DEFAULT_CHAT_GROUP_ID,
    ]
    response = client.put(
        "/chats/groups/order",
        json={"group_ids": group_ids},
    )
    assert response.status_code == 200
    assert [group["id"] for group in response.json()] == group_ids

    response = client.delete(f"/chats/groups/{custom_group['id']}")
    assert response.status_code == 200
    assert response.json()["success"] is True


def test_system_group_cannot_be_deleted(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.delete(f"/chats/groups/{SUBAGENT_CHAT_GROUP_ID}")

    assert response.status_code == 409
