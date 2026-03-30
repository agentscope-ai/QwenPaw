# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest
from agentscope.memory import InMemoryMemory
from agentscope.message import Msg, TextBlock

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
async def test_get_chat_returns_external_agent_history_when_empty():
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
        ],
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


@pytest.mark.asyncio
async def test_get_chat_merges_agent_and_external_history_by_timestamp():
    agent_memory = InMemoryMemory()
    user_msg = Msg(
        name="user",
        role="user",
        content=[TextBlock(type="text", text="normal turn")],
    )
    user_msg.timestamp = "2026-03-29 10:00:00.000"
    user_msg.id = "agent-user-1"
    await agent_memory.add([user_msg])

    external_memory = InMemoryMemory()
    acp_user_msg = Msg(
        name="user",
        role="user",
        content=[TextBlock(type="text", text="/acp opencode inspect")],
    )
    acp_user_msg.timestamp = "2026-03-29 10:01:00.000"
    acp_user_msg.id = "acp-user-1"
    acp_assistant_msg = Msg(
        name="Friday",
        role="assistant",
        content=[TextBlock(type="text", text="acp answer")],
    )
    acp_assistant_msg.timestamp = "2026-03-29 10:01:01.000"
    acp_assistant_msg.id = "acp-assistant-1"
    await external_memory.add([acp_user_msg, acp_assistant_msg])

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
        session=_FakeSession(
            {
                "agent": {"memory": agent_memory.state_dict()},
                "external_agent_memory": external_memory.state_dict(),
            },
        ),
    )

    assert [message.role for message in result.messages] == [
        "user",
        "user",
        "assistant",
    ]
    assert result.messages[0].content[0].text == "normal turn"
    assert result.messages[1].content[0].text == "/acp opencode inspect"
    assert result.messages[2].content[0].text == "acp answer"


@pytest.mark.asyncio
async def test_get_chat_merges_history_stably_without_timestamp():
    agent_memory = InMemoryMemory()
    normal_msg = Msg(
        name="user",
        role="user",
        content=[TextBlock(type="text", text="normal turn")],
    )
    normal_msg.timestamp = ""
    normal_msg.id = "agent-user-1"
    await agent_memory.add([normal_msg])

    external_memory = InMemoryMemory()
    acp_msg = Msg(
        name="Friday",
        role="assistant",
        content=[TextBlock(type="text", text="acp answer")],
    )
    acp_msg.timestamp = ""
    acp_msg.id = "acp-assistant-1"
    await external_memory.add([acp_msg])

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
        session=_FakeSession(
            {
                "agent": {"memory": agent_memory.state_dict()},
                "external_agent_memory": external_memory.state_dict(),
            },
        ),
    )

    assert [message.role for message in result.messages] == [
        "user",
        "assistant",
    ]
    assert result.messages[0].content[0].text == "normal turn"
    assert result.messages[1].content[0].text == "acp answer"
