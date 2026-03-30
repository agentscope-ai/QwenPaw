# -*- coding: utf-8 -*-
"""Tests for memory fallback behavior."""
from agentscope.memory import InMemoryMemory

from copaw.agents.react_agent import CoPawAgent


class _DummyToolkit:
    def __init__(self):
        self.calls = []

    def register_tool_function(self, *args, **kwargs):
        self.calls.append((args, kwargs))


class _NoneMemoryManager:
    chat_model = None
    formatter = None

    def get_in_memory_memory(self):
        return None


def test_setup_memory_manager_keeps_default_memory_when_backend_missing(
    monkeypatch,
):
    """Agent should keep the base InMemoryMemory fallback."""
    monkeypatch.delenv("ENABLE_MEMORY_MANAGER", raising=False)

    agent = CoPawAgent.__new__(CoPawAgent)
    object.__setattr__(agent, "_module_dict", {})
    object.__setattr__(agent, "_attribute_dict", {})
    agent.memory = InMemoryMemory()
    agent.toolkit = _DummyToolkit()
    agent.model = object()
    agent.formatter = object()

    CoPawAgent._setup_memory_manager(
        agent,
        enable_memory_manager=True,
        memory_manager=_NoneMemoryManager(),
        namesake_strategy="skip",
    )

    assert isinstance(agent.memory, InMemoryMemory)
    assert agent._enable_memory_manager is False
    assert agent.memory_manager is None
    assert agent.toolkit.calls == []
