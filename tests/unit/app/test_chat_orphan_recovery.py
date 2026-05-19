# -*- coding: utf-8 -*-
"""Regression tests for orphan chat recovery placeholders."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from qwenpaw.app.runner.api import (
    get_chat_manager,
    get_session,
    get_workspace,
    router,
)
from qwenpaw.app.runner.manager import ChatManager
from qwenpaw.app.runner.models import ChatSpec
from qwenpaw.app.runner.repo.json_repo import JsonChatRepository
from qwenpaw.app.runner.session import SafeJSONSession


class FakeTaskTracker:
    """Minimal task tracker dependency for chat API tests."""

    async def get_status(self, _chat_id: str) -> str:
        return "idle"


class FakeWorkspace:
    """Minimal workspace dependency for chat API tests."""

    task_tracker = FakeTaskTracker()


def get_fake_workspace() -> FakeWorkspace:
    """Return a fake workspace dependency."""
    return FakeWorkspace()


async def test_get_chat_returns_placeholder_initial_messages(
    tmp_path: Path,
) -> None:
    """A chat with only a placeholder session should not open empty."""
    chat_manager = ChatManager(
        repo=JsonChatRepository(tmp_path / "chats.json"),
    )
    session = SafeJSONSession(save_dir=str(tmp_path / "sessions"))
    chat = await chat_manager.create_chat(
        ChatSpec(
            id="chat-1",
            name="Recoverable Chat",
            session_id="console:alice",
            user_id="alice",
            channel="console",
        ),
    )
    await session.ensure_session_placeholder(
        chat.session_id,
        user_id=chat.user_id,
        channel=chat.channel,
        initial_messages=[
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "text", "text": "hello"}],
            },
        ],
    )

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_chat_manager] = lambda: chat_manager
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_workspace] = get_fake_workspace
    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.get(f"/api/chats/{chat.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "idle"
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][0]["content"][0]["text"] == "hello"
