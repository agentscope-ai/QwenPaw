# -*- coding: utf-8 -*-
"""Tests for QwenPawAgent tool timeout registration."""

# pylint: disable=protected-access

from types import SimpleNamespace

from qwenpaw.agents.react_agent import QwenPawAgent
from qwenpaw.tool_calls import ToolCoordinator


def _register_agent_shell_timeout(
    coordinator: ToolCoordinator,
    *,
    agent_id: str,
    timeout: float,
) -> None:
    agent = SimpleNamespace(
        name=agent_id,
        _request_context={
            "tool_coordinator": coordinator,
            "agent_id": agent_id,
        },
        _agent_config=SimpleNamespace(
            running=SimpleNamespace(shell_command_timeout=timeout),
            tools=SimpleNamespace(builtin_tools={}),
        ),
        _get_tool_coordinator=lambda: coordinator,
    )

    QwenPawAgent._register_tool_call_hooks(agent)


def test_shell_timeout_is_registered_per_agent() -> None:
    coordinator = ToolCoordinator()

    _register_agent_shell_timeout(
        coordinator,
        agent_id="agent-a",
        timeout=120.0,
    )
    _register_agent_shell_timeout(
        coordinator,
        agent_id="agent-b",
        timeout=300.0,
    )

    assert (
        coordinator._resolve_timeout(
            "agent-a",
            "execute_shell_command",
            None,
        )
        == 120.0
    )
    assert (
        coordinator._resolve_timeout(
            "agent-b",
            "execute_shell_command",
            None,
        )
        == 300.0
    )
