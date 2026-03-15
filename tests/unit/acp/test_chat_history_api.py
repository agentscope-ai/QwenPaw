# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from agentscope.memory import InMemoryMemory
from agentscope.message import Msg, TextBlock

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from copaw.app.runner.api import get_chat
from copaw.app.runner.models import ChatSpec


class _FakeChatManager:
    def __init__(self, chat: ChatSpec) -> None:
        self.chat = chat

    async def get_chat(self, chat_id: str):
        return self.chat if chat_id == self.chat.id else None


class _FakeSession:
    def __init__(self, state: dict) -> None:
        self.state = state

    async def get_session_state_dict(
        self,
        session_id: str,
        user_id: str = "",
        allow_not_exist: bool = True,
    ) -> dict:
        _ = session_id, user_id, allow_not_exist
        return self.state


@pytest.mark.asyncio
async def test_get_chat_returns_external_agent_history_when_agent_memory_is_empty():
    memory = InMemoryMemory()
    await memory.add(
        [
            Msg(
                name="user",
                role="user",
                content=[TextBlock(type="text", text="inspect this repo")],
            ),
            Msg(
                name="Friday",
                role="assistant",
                content=[TextBlock(type="text", text="final answer")],
            ),
        ]
    )

    chat = ChatSpec(
        id="chat-1",
        name="Test",
        session_id="session-1",
        user_id="user-1",
        channel="console",
        meta={},
    )

    result = await get_chat(
        chat_id="chat-1",
        mgr=_FakeChatManager(chat),
        session=_FakeSession({"external_agent_memory": memory.state_dict()}),
    )

    assert len(result.messages) == 2
    assert result.messages[0].role == "user"
    assert result.messages[1].role == "assistant"
