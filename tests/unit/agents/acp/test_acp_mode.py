# -*- coding: utf-8 -*-
"""Tests for ACP ``--mode`` first-message prefixing."""
# pylint: disable=protected-access,unused-argument
from __future__ import annotations

from types import SimpleNamespace

import pytest
from acp import RequestError
from agentscope.message import Msg, TextBlock

from qwenpaw.app.agent_context import scoped_session_id
from qwenpaw.app.workspace.workspace_plugins import WorkspacePlugins
from qwenpaw.config.config import (
    CustomLoopModeConfig,
    GateInstanceConfig,
    LoopConfig,
)
from qwenpaw.modes.base import AgentMode
from qwenpaw.modes.custom_loop import load_custom_loop_modes
from qwenpaw.modes.goal import GoalMode
from qwenpaw.modes.mission import MissionMode
from qwenpaw.runtime.slash_command_registry import CommandSpec

from qwenpaw.agents.acp.server import QwenPawACPAgent


def _workspace(custom_modes=()):
    """Build the same mode registries used by both entry points."""
    workspace = SimpleNamespace(
        config=SimpleNamespace(
            running=SimpleNamespace(
                loop=LoopConfig(custom_modes=custom_modes),
            ),
        ),
        plugins=WorkspacePlugins(),
    )
    workspace.plugins.register_mode(GoalMode(), workspace)
    load_custom_loop_modes(workspace)
    return workspace


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
    assert (
        agent._apply_mode("hello world", "s1", _workspace()) == "hello world"
    )
    assert agent._apply_mode("/goal task", "s1", _workspace()) == "/goal task"


@pytest.mark.parametrize(f"mode_id", [f"goal", f"mission"])
def test_first_message_gets_registered_mode_prefix(mode_id):
    workspace = _workspace()
    workspace.plugins.register_mode(MissionMode(), workspace)
    agent = _make_agent(mode=mode_id)
    assert agent._apply_mode(f"find the answer", f"s1", workspace) == (
        f"/{mode_id} find the answer"
    )


def test_only_first_message_is_prefixed():
    agent = _make_agent()
    agent._apply_mode("find the answer", "s1", _workspace())
    assert agent._apply_mode("keep going", "s1", _workspace()) == "keep going"


def test_slash_prefixed_first_message_is_untouched():
    agent = _make_agent()
    assert agent._apply_mode("/new start over", "s1", _workspace()) == (
        "/new start over"
    )
    # The first message consumed the mode slot.
    assert (
        agent._apply_mode("plain follow-up", "s1", _workspace())
        == "plain follow-up"
    )


def test_existing_goal_command_is_not_doubled():
    agent = _make_agent()
    assert agent._apply_mode("/goal already a goal", "s1", _workspace()) == (
        "/goal already a goal"
    )


def test_sessions_are_independent():
    agent = _make_agent()
    agent._apply_mode("first", "s1", _workspace())
    assert agent._apply_mode("second session", "s2", _workspace()) == (
        "/goal second session"
    )


async def test_load_session_disables_prefix():
    agent = _make_agent()
    _patch_lifecycle(agent)
    await agent.load_session(cwd="/tmp", session_id="s1")
    assert agent._apply_mode("hello", "s1", _workspace()) == "hello"


async def test_resume_session_disables_prefix():
    agent = _make_agent()
    _patch_lifecycle(agent)
    await agent.resume_session(cwd="/tmp", session_id="s1")
    assert agent._apply_mode("hello", "s1", _workspace()) == "hello"


async def test_close_session_discards_marker():
    agent = _make_agent()
    _patch_lifecycle(agent)
    agent._apply_mode("first", "s1", _workspace())
    await agent.close_session(session_id="s1")
    assert agent._apply_mode("restart", "s1", _workspace()) == "/goal restart"


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
        PluginRegistry().unregister_stop_workspace("default", workspace)


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
        PluginRegistry().unregister_stop_workspace("default", workspace)


async def test_workspace_failure_does_not_consume_mode(monkeypatch):
    """Retrying initialization must still activate the requested mode."""
    from acp import text_block

    agent = _make_agent()

    async def fail():
        raise OSError(f"Temporary workspace failure")

    monkeypatch.setattr(agent, f"_ensure_workspace", fail)
    with pytest.raises(OSError):
        await agent.prompt([text_block(f"Solve")], f"retry")
    assert (
        agent._apply_mode(f"Solve", f"retry", _workspace()) == f"/goal Solve"
    )


async def test_stop_bridge_preserves_other_workspaces():
    """Closing one ACP agent must not clear another agent or the app."""
    from qwenpaw.plugins.registry import PluginRegistry

    registry = PluginRegistry()
    previous = registry.get_workspace_manager()
    app = SimpleNamespace(
        plugins=SimpleNamespace(stop_handlers=[object()]),
    )
    manager = SimpleNamespace(agents={f"app": app})
    registry.set_workspace_manager(manager)
    first, second = _make_agent(), _make_agent()
    first._install_stop_gate_bridge(f"one", app)
    second._install_stop_gate_bridge(f"two", app)
    try:
        await first._shutdown_workspace()
        assert registry.get_workspace_manager() is manager
        assert registry.get_stop_handlers(f"app") == app.plugins.stop_handlers
        assert registry.get_stop_handlers(f"two") == app.plugins.stop_handlers
    finally:
        await first._shutdown_workspace()
        await second._shutdown_workspace()
        registry.set_workspace_manager(previous)


async def test_custom_mode_uses_shared_catalog_and_existing_dispatch(
    monkeypatch,
):
    """A mode ID differing from its command works through HTTP and ACP."""
    from unittest.mock import AsyncMock
    from qwenpaw.app.routers import loops

    config = CustomLoopModeConfig(
        id=f"quality-id",
        name=f"Quality",
        enabled=True,
        slash_command=f"verify",
        gates=[GateInstanceConfig(id=f"limit", type=f"iteration")],
    )
    workspace = _workspace([config])
    monkeypatch.setattr(
        loops,
        f"get_agent_for_request",
        AsyncMock(return_value=workspace),
    )
    catalog = await loops.list_loops(None)
    selected = next(
        mode for mode in catalog if mode.id == f"custom:quality-id"
    )
    assert selected.slash_command == f"verify"

    agent = _make_agent(mode=selected.id)
    text = agent._apply_mode(f"Check the result", f"custom-session", workspace)
    assert text == f"/verify Check the result"
    ctx = SimpleNamespace(
        session_id=f"custom-session",
        workspace=workspace,
        input_msgs=[
            Msg(
                name=f"user",
                role=f"user",
                content=[TextBlock(type=f"text", text=text)],
            ),
        ],
    )
    with scoped_session_id(ctx.session_id):
        result = await workspace.plugins.slash_command_registry.dispatch(
            text,
            ctx,
        )
        assert result is None
        assert workspace.plugins.active_mode_names(ctx) == {selected.id}
        assert any(reg.is_active() for reg in workspace.plugins.stop_handlers)
        assert ctx.input_msgs[0].content[0].text == f"Check the result"
    assert (
        agent._apply_mode(f"Continue", ctx.session_id, workspace)
        == f"Continue"
    )


async def test_plugin_mode_uses_its_registered_command():
    """Plugin mode names do not need to match their entry command."""
    activated = []

    async def activate(ctx, args):
        activated.append(args)

    class ReviewMode(AgentMode):
        name = f"review"

        def commands(self):
            return [CommandSpec(name=f"inspect", handler=activate)]

    workspace = _workspace()
    workspace.plugins.register_mode(ReviewMode(), workspace)
    agent = _make_agent(mode=f"plugin:review")
    text = agent._apply_mode(f"Check changes", f"plugin-session", workspace)
    assert text == f"/inspect Check changes"
    await workspace.plugins.slash_command_registry.dispatch(text, None)
    assert activated == [f"Check changes"]


@pytest.mark.parametrize(
    f"mode_id",
    [f"missing", f"custom:disabled", f"mission"],
)
def test_unavailable_mode_does_not_consume_first_message(mode_id):
    """Unavailable modes must fail without consuming the first message."""
    workspace = _workspace(
        [
            CustomLoopModeConfig(
                id=f"disabled",
                name=f"Disabled",
                slash_command=f"disabled",
                enabled=False,
                gates=[GateInstanceConfig(id=f"limit", type=f"iteration")],
            ),
        ],
    )
    agent = _make_agent(mode=mode_id)
    with pytest.raises(RequestError):
        agent._apply_mode(f"Do work", f"retry", workspace)
    assert f"retry" not in agent._mode_started


def test_default_mode_preserves_user_message():
    agent = _make_agent(mode=f"default")
    assert (
        agent._apply_mode(f"Do work", f"default", _workspace()) == f"Do work"
    )
