# -*- coding: utf-8 -*-
"""Console attachment execution and saved transcript regression tests."""

# pylint: disable=protected-access
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentscope.agent import Agent
from agentscope.message import Msg
from agentscope.state import AgentState

from qwenpaw.app.channels.console.channel import ConsoleChannel
from qwenpaw.app.chats.api import get_chat
from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.app.chats.session import SafeJSONSession
from qwenpaw.app.chats.utils import agentscope_msg_to_message
from qwenpaw.constant import (
    QWENPAW_CLIENT_MESSAGE_ID_KEY,
    QWENPAW_USER_CONTENT_KEY,
)
from qwenpaw.runtime._state_utils import StateProxy
from qwenpaw.runtime.message_convert import _request_input_to_msgs
from qwenpaw.schemas import ContentType, Event, FileContent, TextContent


@pytest.mark.asyncio
@pytest.mark.parametrize("with_text", [False, True])
async def test_console_file_survives_agent_ingestion_and_disk_history(
    tmp_path,
    with_text,
):
    """Use real AgentScope input rewriting, without invoking a model."""
    session = SafeJSONSession(save_dir=str(tmp_path / "sessions"))
    received = []

    async def process(request):
        received.append(request)
        messages = _request_input_to_msgs(request.input)
        agent = SimpleNamespace(
            state=AgentState(),
            model=SimpleNamespace(
                formatter=SimpleNamespace(supported_input_media_types=[]),
            ),
            offloader=None,
        )
        await Agent._handle_incoming_messages(agent, messages)
        assert all(
            block.type == "text" for block in agent.state.context[0].content
        )
        state = StateProxy()
        state.data = {"state": agent.state.model_dump(mode="json")}
        await session.save_session_state(
            session_id=request.session_id,
            user_id=request.user_id,
            channel=request.channel,
            agent=state,
        )
        yield Event(object="response", status="completed", output=[])

    channel = ConsoleChannel(
        process=process,
        enabled=True,
        bot_prefix="",
        media_dir=str(tmp_path / "media"),
    )
    file_path = str(tmp_path / "media" / "input.txt")
    content = [
        FileContent(
            file_url=file_path,
            file_name="input.txt",
            file_size=24,
        ),
    ]
    content.insert(
        0,
        TextContent(text="read this file" if with_text else ""),
    )
    events = [
        event
        async for event in channel.stream_one(
            {
                "sender_id": "user-1",
                "content_parts": content,
                "message_metadata": {
                    QWENPAW_CLIENT_MESSAGE_ID_KEY: "client-file-1",
                },
                "meta": {"session_id": "session-1"},
            },
        )
    ]

    assert len(received) == 1
    assert events
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
        session=SafeJSONSession(save_dir=str(tmp_path / "sessions")),
        workspace=SimpleNamespace(
            config=SimpleNamespace(backend="qwenpaw"),
            task_tracker=SimpleNamespace(
                get_status=AsyncMock(return_value="idle"),
            ),
        ),
    )

    assert history.status == "idle"
    assert len(history.messages) == 1
    message = history.messages[0]
    assert len(message.content) == (2 if with_text else 1)
    attachment = message.content[-1]
    assert attachment.type == ContentType.FILE
    assert attachment.file_url == file_path
    assert attachment.file_name == "input.txt"
    assert attachment.file_size == 24
    if with_text:
        assert message.content[0].text == "read this file"
    assert message.metadata["metadata"][QWENPAW_CLIENT_MESSAGE_ID_KEY] == (
        "client-file-1"
    )
    assert QWENPAW_USER_CONTENT_KEY not in message.metadata["metadata"]
    assert "system-reminder" not in message.model_dump_json()


@pytest.mark.parametrize(
    "original",
    [None, [], "broken", [{"type": "unknown", "text": "bad"}]],
)
def test_missing_or_invalid_original_content_uses_legacy_history(original):
    msg = Msg(
        name="user",
        role="user",
        content=[{"type": "text", "text": "legacy text"}],
        metadata={QWENPAW_USER_CONTENT_KEY: original},
    )

    [message] = agentscope_msg_to_message(msg)

    assert message.content[0].text == "legacy text"
