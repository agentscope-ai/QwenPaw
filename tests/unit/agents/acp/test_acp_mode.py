# -*- coding: utf-8 -*-
"""Tests for ACP ``--mode`` first-message prefixing."""
# pylint: disable=protected-access,unused-argument
from __future__ import annotations

from types import SimpleNamespace

from qwenpaw.agents.acp.server import QwenPawACPAgent


def _make_agent(mode: str | None = "goal") -> QwenPawACPAgent:
    return QwenPawACPAgent(mode=mode)


def _patch_lifecycle(agent: QwenPawACPAgent) -> None:
    """Neutralize session lifecycle helpers that touch MCP/workspace."""

    async def _noop(*args: object, **kwargs: object) -> None:
        return None

    agent._cancel_active_prompt = _noop  # type: ignore[method-assign]
    agent._cancel_pending_approvals = _noop  # type: ignore[method-assign]
    agent._remove_session_mcp = _noop  # type: ignore[method-assign]
    agent._sync_session_mcp = _noop  # type: ignore[method-assign]
    agent._advertise_commands = _noop  # type: ignore[method-assign]


def test_mode_none_passes_text_through():
    agent = _make_agent(mode=None)
    assert agent._apply_mode("hello world", "s1") == "hello world"
    assert agent._apply_mode("/goal task", "s1") == "/goal task"


def test_first_message_gets_goal_prefix():
    agent = _make_agent()
    assert agent._apply_mode("find the answer", "s1") == (
        "/goal find the answer"
    )


def test_only_first_message_is_prefixed():
    agent = _make_agent()
    agent._apply_mode("find the answer", "s1")
    assert agent._apply_mode("keep going", "s1") == "keep going"


def test_slash_prefixed_first_message_is_untouched():
    agent = _make_agent()
    assert agent._apply_mode("/new start over", "s1") == ("/new start over")
    # The first message consumed the mode slot.
    assert agent._apply_mode("plain follow-up", "s1") == "plain follow-up"


def test_existing_goal_command_is_not_doubled():
    agent = _make_agent()
    assert agent._apply_mode("/goal already a goal", "s1") == (
        "/goal already a goal"
    )


def test_sessions_are_independent():
    agent = _make_agent()
    agent._apply_mode("first", "s1")
    assert agent._apply_mode("second session", "s2") == (
        "/goal second session"
    )


async def test_load_session_disables_prefix():
    agent = _make_agent()
    _patch_lifecycle(agent)
    await agent.load_session(cwd="/tmp", session_id="s1")
    assert agent._apply_mode("hello", "s1") == "hello"


async def test_resume_session_disables_prefix():
    agent = _make_agent()
    _patch_lifecycle(agent)
    await agent.resume_session(cwd="/tmp", session_id="s1")
    assert agent._apply_mode("hello", "s1") == "hello"


async def test_close_session_discards_marker():
    agent = _make_agent()
    _patch_lifecycle(agent)
    agent._apply_mode("first", "s1")
    await agent.close_session(session_id="s1")
    assert agent._apply_mode("restart", "s1") == "/goal restart"


def test_stop_gate_bridge_exposes_workspace_handlers():
    agent = _make_agent()
    handler = object()
    workspace = SimpleNamespace(
        plugins=SimpleNamespace(stop_handlers=[handler]),
    )
    from qwenpaw.plugins.registry import PluginRegistry

    try:
        agent._install_stop_gate_bridge("default", workspace)
        assert PluginRegistry.get_stop_handlers(
            agent_id="default",
        ) == [handler]
        assert not PluginRegistry.get_stop_handlers(agent_id="other")
    finally:
        PluginRegistry().set_workspace_manager(None)


def test_stop_gate_bridge_cleared_on_shutdown():
    agent = _make_agent()
    workspace = SimpleNamespace(
        plugins=SimpleNamespace(stop_handlers=[object()]),
    )
    from qwenpaw.plugins.registry import PluginRegistry

    agent._install_stop_gate_bridge("default", workspace)
    try:
        import asyncio

        asyncio.run(agent._shutdown_workspace())
        assert not PluginRegistry.get_stop_handlers(agent_id="default")
    finally:
        PluginRegistry().set_workspace_manager(None)
