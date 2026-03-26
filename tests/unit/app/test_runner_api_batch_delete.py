# -*- coding: utf-8 -*-
from fastapi import FastAPI
from fastapi.testclient import TestClient

from copaw.app.runner.api import get_chat_manager, router


class StubChatManager:
    def __init__(self, deleted: bool = True) -> None:
        self.deleted = deleted
        self.received_chat_ids: list[str] | None = None

    async def delete_chats(self, chat_ids: list[str]) -> bool:
        self.received_chat_ids = chat_ids
        return self.deleted


def create_test_client(chat_manager: StubChatManager) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_chat_manager] = lambda: chat_manager
    return TestClient(app)


def test_batch_delete_chats_accepts_chat_ids_object() -> None:
    chat_manager = StubChatManager()
    client = create_test_client(chat_manager)

    response = client.post(
        "/chats/batch-delete",
        json={"chat_ids": ["chat-1", "chat-2"]},
    )

    assert response.status_code == 200
    assert response.json() == {"deleted": True}
    assert chat_manager.received_chat_ids == ["chat-1", "chat-2"]


def test_batch_delete_chats_rejects_raw_array_body() -> None:
    chat_manager = StubChatManager()
    client = create_test_client(chat_manager)

    response = client.post(
        "/chats/batch-delete",
        json=["chat-1", "chat-2"],
    )

    assert response.status_code == 422
    assert chat_manager.received_chat_ids is None
