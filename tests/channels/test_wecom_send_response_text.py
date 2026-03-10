# -*- coding: utf-8 -*-

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    path_str = str(candidate)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from agentscope_runtime.engine.schemas.agent_schemas import (
    AgentResponse,
    ContentType,
    Message,
    MessageType,
    Role,
    TextContent,
)

from copaw.app.channels.wecom.channel import WeComChannel


def _response(text: str) -> AgentResponse:
    return AgentResponse(
        output=[
            Message(
                type=MessageType.MESSAGE,
                role=Role.ASSISTANT,
                content=[TextContent(type=ContentType.TEXT, text=text)],
            )
        ]
    )


def test_send_response_uses_sender_for_text() -> None:
    channel = WeComChannel()

    asyncio.run(
        channel.send_response("wecom:user:alice", _response("hello"), meta={})
    )

    assert channel._sender.last_target.target_id == "alice"
    assert channel._sender.last_payload["msgtype"] == "text"
    assert channel._sender.last_payload["text"]["content"].endswith("hello")
