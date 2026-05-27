# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from types import SimpleNamespace

from agentscope.message import Msg

from qwenpaw.agents.context.agent_context import AgentContext
from qwenpaw.agents.react_agent import QwenPawAgent
from qwenpaw.agents.utils.estimate_token_counter import EstimatedTokenCounter


def test_media_strip_notifies_context_rewritten() -> None:
    events: list[str] = []
    memory = AgentContext(
        token_counter=EstimatedTokenCounter(),
        on_context_rewritten=lambda: events.append("rewritten"),
    )
    memory.content.append(
        (
            Msg(
                name="user",
                role="user",
                content=[
                    {"type": "text", "text": "hello"},
                    {"type": "image", "url": "file:///tmp/a.png"},
                ],
            ),
            [],
        ),
    )
    agent = SimpleNamespace(
        memory=memory,
        _MEDIA_BLOCK_TYPES={"image", "audio", "video"},
    )

    stripped = QwenPawAgent._strip_media_blocks_from_memory(agent)

    assert stripped == 1
    assert events == ["rewritten"]
