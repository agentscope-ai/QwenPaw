# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Agent-level tests for compression strategy middleware wiring."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from agentscope.agent import Agent, ContextConfig
from agentscope.message import HintBlock, Msg, TextBlock

from qwenpaw.agents.middlewares import MemoryMiddleware
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
        self._turn_state: dict[str, Any] = {
            "pending": ["turn-1"],
            "seen": {"turn-1": None},
            "touched_at": 0,
        }

    def get_memory_prompt(self) -> str:
        return ""

    def get_memory_config(self) -> Any:
        return SimpleNamespace(summarize_when_compact=True)

    def get_auto_memory_turn_state(self, _session_id: str) -> dict[str, Any]:
        return self._turn_state

    @property
    def pending(self) -> list[str]:
        return self._turn_state["pending"]

    async def auto_memory(self, _messages: list[Msg], **_kwargs: Any) -> None:
        self._events.append("auto_memory")


class _ScrollManager:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self.instructions: HintBlock | None = None

    async def compress(
        self,
        _agent: Any,
        _context_config: Any = None,
        instructions: HintBlock | None = None,
    ) -> None:
        self.instructions = instructions
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
    return agent


@pytest.mark.asyncio
async def test_scroll_runs_auto_memory_middleware_before_eviction() -> None:
    """Scroll must not bypass AgentScope's compression middleware chain."""
    events: list[str] = []
    memory_manager = _MemoryManager(events)
    scroll_manager = _ScrollManager(events)
    agent = _scroll_agent(memory_manager, scroll_manager)

    instructions = HintBlock(hint="preserve decisions", source="user")
    await agent.compress_context(instructions=instructions)

    assert events == ["auto_memory", "scroll"]
    assert scroll_manager.instructions is instructions
    assert not memory_manager.pending
