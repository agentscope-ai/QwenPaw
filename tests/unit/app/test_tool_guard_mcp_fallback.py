# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field

from copaw.agents.tool_guard_mixin import ToolGuardMixin


@dataclass
class _MemoryStub:
    added: list = field(default_factory=list)

    async def add(self, msg, marks=None):
        _ = marks
        self.added.append(msg)


class _BaseRaisesMcp:
    async def _acting(self, tool_call):
        _ = tool_call
        raise RuntimeError(
            "The MCP client is not connected to the server. "
            "Use the connect() method first.",
        )


class _BaseRaisesGeneric:
    async def _acting(self, tool_call):
        _ = tool_call
        raise RuntimeError("generic tool failure")


class _AgentMcpFallback(ToolGuardMixin, _BaseRaisesMcp):
    def __init__(self):
        self._tool_guard_engine = type("Engine", (), {"enabled": False})()
        self._tool_guard_approval_service = object()
        self._request_context = {"session_id": "s1"}
        self.memory = _MemoryStub()
        self.printed = []

    async def print(self, msg, flush):
        _ = flush
        self.printed.append(msg)


class _AgentGenericError(ToolGuardMixin, _BaseRaisesGeneric):
    def __init__(self):
        self._tool_guard_engine = type("Engine", (), {"enabled": False})()
        self._tool_guard_approval_service = object()
        self._request_context = {"session_id": "s1"}
        self.memory = _MemoryStub()

    async def print(self, msg, flush):
        _ = msg, flush


async def test_mcp_connection_error_degrades_to_tool_result() -> None:
    agent = _AgentMcpFallback()
    tool_call = {"id": "call_1", "name": "web_search", "input": {}}

    result = await agent._acting(tool_call)

    assert result is None
    assert len(agent.printed) == 1
    assert len(agent.memory.added) == 1
    text = str(agent.memory.added[0].content)
    assert "工具调用失败" in text
    assert "mcp" not in text.lower()


async def test_non_mcp_error_still_raises() -> None:
    agent = _AgentGenericError()
    tool_call = {"id": "call_2", "name": "web_search", "input": {}}

    raised = False
    try:
        await agent._acting(tool_call)
    except RuntimeError as exc:
        raised = True
        assert "generic tool failure" in str(exc)

    assert raised is True
