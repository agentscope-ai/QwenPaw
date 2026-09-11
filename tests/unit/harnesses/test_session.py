# -*- coding: utf-8 -*-
"""Tests for materialized third-party Agent sessions."""

from pathlib import Path

import pytest
from agentscope.state import AgentState

from qwenpaw.app.chats.session import SafeJSONSession
from qwenpaw.app.chats.utils import agentscope_msg_to_message
from qwenpaw.harnesses.session import HarnessSessionBridge
from qwenpaw.schemas import (
    AgentRequest,
    AgentResponse,
    AudioContent,
    DataContent,
    FileContent,
    ImageContent,
    Message,
    MessageType,
    Role,
    RunStatus,
    TextContent,
    VideoContent,
)


@pytest.mark.asyncio
async def test_bridge_persists_refreshable_reasoning_and_tools(
    tmp_path: Path,
) -> None:
    session = SafeJSONSession(str(tmp_path))
    bridge = HarnessSessionBridge(session)
    request = AgentRequest(
        session_id="chat-1",
        user_id="user-1",
        input=[
            Message(
                role=Role.USER,
                content=[TextContent(text="Fix it")],
            ),
        ],
    )
    reasoning = Message(
        type=MessageType.REASONING,
        role=Role.ASSISTANT,
        status=RunStatus.Completed,
        content=[TextContent(text="Checking")],
    )
    tool_call = Message(
        type=MessageType.PLUGIN_CALL,
        role=Role.ASSISTANT,
        status=RunStatus.Completed,
        content=[
            DataContent(
                data={
                    "call_id": "tool-1",
                    "name": "shell",
                    "arguments": '{"command":"pytest"}',
                },
            ),
        ],
    )
    tool_output = Message(
        type=MessageType.PLUGIN_CALL_OUTPUT,
        role=Role.TOOL,
        status=RunStatus.Completed,
        content=[
            DataContent(
                data={
                    "call_id": "tool-1",
                    "name": "shell",
                    "output": "1 passed",
                },
            ),
        ],
    )
    answer = Message(
        type=MessageType.MESSAGE,
        role=Role.ASSISTANT,
        status=RunStatus.Completed,
        content=[TextContent(text="Done")],
    )
    response = AgentResponse(
        id="response-1",
        output=[reasoning, tool_call, tool_output, answer],
        status=RunStatus.Completed,
    )

    await bridge.append_turn(
        request=request,
        response=response,
        backend="codex",
    )

    persisted = await session.get_session_state_dict(
        "chat-1",
        "user-1",
    )
    state = AgentState.model_validate(persisted["agent"]["state"])
    restored = agentscope_msg_to_message(list(state.context))

    assert [message.type for message in restored] == [
        MessageType.MESSAGE,
        MessageType.REASONING,
        MessageType.PLUGIN_CALL,
        MessageType.PLUGIN_CALL_OUTPUT,
        MessageType.MESSAGE,
    ]
    assert restored[1].content[0].text == "Checking"
    assert restored[3].content[0].data["output"] == "1 passed"


@pytest.mark.asyncio
async def test_bridge_persists_attachment_only_message(
    tmp_path: Path,
) -> None:
    session = SafeJSONSession(str(tmp_path))
    bridge = HarnessSessionBridge(session)
    image_path = tmp_path / "screen.png"
    file_path = tmp_path / "notes.txt"
    audio_path = tmp_path / "voice.mp3"
    video_path = tmp_path / "demo.mp4"
    request = AgentRequest(
        session_id="chat-1",
        user_id="user-1",
        input=[
            Message(
                role=Role.USER,
                content=[
                    ImageContent(image_url=str(image_path)),
                    FileContent(
                        filename="notes.txt",
                        file_url=str(file_path),
                    ),
                    AudioContent(data=str(audio_path), format="mp3"),
                    VideoContent(video_url=str(video_path)),
                ],
            ),
        ],
    )
    response = AgentResponse(
        id="response-1",
        output=[],
        status=RunStatus.Completed,
    )

    await bridge.append_turn(
        request=request,
        response=response,
        backend="codex",
    )

    persisted = await session.get_session_state_dict(
        "chat-1",
        "user-1",
    )
    state = AgentState.model_validate(persisted["agent"]["state"])
    restored = agentscope_msg_to_message(list(state.context))

    assert len(restored) == 1
    assert [content.type for content in restored[0].content] == [
        "image",
        "file",
        "audio",
        "video",
    ]
    assert Path(restored[0].content[0].image_url) == image_path
    assert Path(restored[0].content[1].file_url) == file_path
    assert Path(restored[0].content[2].data) == audio_path
    assert Path(restored[0].content[3].video_url) == video_path
