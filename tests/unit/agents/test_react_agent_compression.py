# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Agent-level tests for compression strategy middleware wiring."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from agentscope.agent import Agent, ContextConfig, ReActConfig
from agentscope.message import HintBlock, Msg, TextBlock
from agentscope.tool import Toolkit

from qwenpaw.agents.command_handler import CommandHandler
from qwenpaw.agents.middlewares import (
    MemoryMiddleware,
    auto_memory_turn_state,
)
from qwenpaw.agents.react_agent import QwenPawAgent
from qwenpaw.constant import (
    EXTERNAL_USER_QUERY_MESSAGE_TAG,
    QWENPAW_MESSAGE_TAG_KEY,
)


class _TokenModel:
    context_size = 100

    async def count_tokens(self, **_kwargs: Any) -> int:
        return 90


class _MemoryManager:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self.enabled = True
        self.submitted: list[list[str]] = []

    def get_memory_prompt(self) -> str:
        return ""

    async def auto_memory(self, _messages: list[Msg], **_kwargs: Any) -> None:
        self._events.append("auto_memory")

    def add_summarize_task(
        self,
        messages: list[Msg],
        **_kwargs: Any,
    ) -> None:
        self._events.append("handler_memory")
        self.submitted.append([msg.get_text_content() for msg in messages])


def test_qwenpaw_agent_disables_runtime_state_injection() -> None:
    """The AgentScope 2.0.6 opt-in must preserve QwenPaw's old prompts."""
    agent = QwenPawAgent(
        name="QwenPaw",
        model=_TokenModel(),
        system_prompt="",
        toolkit=Toolkit(tools=[]),
        react_config=ReActConfig(),
        middlewares=[],
        agent_config=SimpleNamespace(language="en-US"),
    )

    assert agent.injection_config.inject_runtime_state is False


class _ScrollManager:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self.instructions: HintBlock | None = None
        self.last_compress = {"evicted": 0, "folded": 0}

    async def compress(
        self,
        _agent: Any,
        _context_config: Any = None,
        instructions: HintBlock | None = None,
    ) -> None:
        self.instructions = instructions
        self.last_compress["evicted"] = 1
        self._events.append("scroll")


def _scroll_agent(
    memory_manager: _MemoryManager,
    scroll_manager: _ScrollManager,
) -> QwenPawAgent:
    agent = object.__new__(QwenPawAgent)
    Agent.__init__(
        agent,
        name="QwenPaw",
        system_prompt="",
        model=_TokenModel(),
        middlewares=[MemoryMiddleware(memory_manager=memory_manager)],
        context_config=ContextConfig(trigger_ratio=0.5, reserve_ratio=0.1),
    )
    agent._agent_config = SimpleNamespace(
        running=SimpleNamespace(
            light_context_config=SimpleNamespace(
                context_compact_config=SimpleNamespace(enabled=True),
            ),
        ),
    )
    agent._request_context = {
        "source": "user",
        "session_id": "session-1",
    }
    agent._context_manager = scroll_manager
    agent.state.session_id = "session-1"
    user = Msg(
        name="user",
        role="user",
        content=[TextBlock(type="text", text="remember this")],
        metadata={
            QWENPAW_MESSAGE_TAG_KEY: EXTERNAL_USER_QUERY_MESSAGE_TAG,
        },
    )
    user.id = "turn-1"
    agent.state.context = [user]
    turn_state = auto_memory_turn_state(agent.state)
    turn_state["pending"] = ["turn-1"]
    turn_state["seen"] = {"turn-1": None}
    return agent


@pytest.mark.asyncio
async def test_scroll_runs_before_auto_memory() -> None:
    """Scroll must not bypass AgentScope's compression middleware chain."""
    events: list[str] = []
    memory_manager = _MemoryManager(events)
    scroll_manager = _ScrollManager(events)
    agent = _scroll_agent(memory_manager, scroll_manager)

    instructions = HintBlock(hint="preserve decisions", source="user")
    await agent.compress_context(instructions=instructions)

    assert events == ["scroll", "auto_memory"]
    assert scroll_manager.instructions is instructions
    assert not auto_memory_turn_state(agent.state)["pending"]


@pytest.mark.asyncio
async def test_manual_compact_submits_auto_memory_once() -> None:
    """The command handler, not compression middleware, owns manual memory."""
    events: list[str] = []
    memory_manager = _MemoryManager(events)
    scroll_manager = _ScrollManager(events)
    agent = _scroll_agent(memory_manager, scroll_manager)
    agent.state.context.append(
        Msg(
            name="QwenPaw",
            role="assistant",
            content=[TextBlock(type="text", text="answer-1")],
        ),
    )
    handler = CommandHandler(
        agent_name="QwenPaw",
        agent=agent,
        memory_manager=memory_manager,
    )
    handler._get_agent_config = lambda: SimpleNamespace(
        running=SimpleNamespace(
            light_context_config=SimpleNamespace(
                strategy="scroll",
                context_compact_config=SimpleNamespace(enabled=True),
            ),
        ),
    )

    await handler.handle_command("/compact")

    assert events == ["scroll", "handler_memory"]
    assert memory_manager.submitted == [["remember this", "answer-1"]]
    assert not auto_memory_turn_state(agent.state)["pending"]
