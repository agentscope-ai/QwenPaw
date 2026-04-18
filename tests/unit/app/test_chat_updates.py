# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
"""Regression tests for chat update semantics."""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from qwenpaw.app.runner import manager as chat_manager_module
from qwenpaw.app.runner.api import get_chat_manager, router
from qwenpaw.app.runner.manager import ChatManager
from qwenpaw.app.runner.models import ChatSpec, ChatUpdate
from qwenpaw.app.runner.repo.json_repo import JsonChatRepository


@pytest.fixture
def chat_manager(tmp_path: Path) -> ChatManager:
    """Create a chat manager backed by a temporary chats.json file."""
    return ChatManager(repo=JsonChatRepository(tmp_path / "chats.json"))


@pytest.fixture
def api_client(chat_manager: ChatManager) -> AsyncClient:
    """Create an isolated chat API client."""
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_chat_manager] = lambda: chat_manager
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


async def _seed_chat(chat_manager: ChatManager) -> ChatSpec:
    """Create a representative persisted chat."""
    spec = ChatSpec(
        id="chat-1",
        name="Old Chat",
        session_id="console:default",
        user_id="default",
        channel="console",
        meta={"source": "test"},
    )
    return await chat_manager.create_chat(spec)


async def test_put_chat_accepts_partial_rename_payload(
    api_client: AsyncClient,
    chat_manager: ChatManager,
) -> None:
    """PUT rename should merge into the stored chat.

    This should not require callers to send a full ChatSpec.
    """
    chat = await _seed_chat(chat_manager)

    async with api_client:
        response = await api_client.put(
            f"/api/chats/{chat.id}",
            json={"name": "Renamed Chat"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == chat.id
    assert body["name"] == "Renamed Chat"
    assert body["session_id"] == chat.session_id
    assert body["user_id"] == chat.user_id
    assert body["channel"] == chat.channel

    saved = await chat_manager.get_chat(chat.id)
    assert saved is not None
    assert saved.name == "Renamed Chat"
    assert saved.meta == {"source": "test"}


@pytest.mark.parametrize(
    "payload",
    [
        {"id": "chat-1"},
        {"session_id": "console:other"},
    ],
)
async def test_put_chat_rejects_read_only_fields(
    api_client: AsyncClient,
    chat_manager: ChatManager,
    payload: dict[str, str],
) -> None:
    """PUT should reject read-only chat identity fields."""
    chat = await _seed_chat(chat_manager)

    async with api_client:
        response = await api_client.put(
            f"/api/chats/{chat.id}",
            json=payload,
        )

    assert response.status_code == 422

    saved = await chat_manager.get_chat(chat.id)
    assert saved is not None
    assert saved.session_id == chat.session_id


async def test_touch_chat_updates_timestamp_without_overwriting_name(
    chat_manager: ChatManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Touching a chat for activity bookkeeping should preserve title."""
    chat = await _seed_chat(chat_manager)

    renamed = await chat_manager.patch_chat(
        chat.id,
        ChatUpdate(name="Renamed Chat"),
    )
    assert renamed is not None

    renamed_after_update = await chat_manager.get_chat(chat.id)
    assert renamed_after_update is not None
    previous_updated_at = renamed_after_update.updated_at

    class FixedDateTime:
        """Deterministic clock for timestamp-sensitive assertions."""

        @classmethod
        def now(cls, tz=None):
            assert tz == previous_updated_at.tzinfo
            return previous_updated_at + timedelta(seconds=1)

    monkeypatch.setattr(chat_manager_module, "datetime", FixedDateTime)

    touch_chat = getattr(chat_manager, "touch_chat", None)
    assert callable(touch_chat)
    await touch_chat(chat.id)

    saved = await chat_manager.get_chat(chat.id)
    assert saved is not None
    assert saved.name == "Renamed Chat"
    assert saved.updated_at > previous_updated_at
