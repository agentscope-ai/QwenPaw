# -*- coding: utf-8 -*-
"""Tests for entering the selected ACP runtime mode."""

# pylint: disable=protected-access,unused-argument
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from acp import RequestError, text_block
from agentscope.message import Msg, TextBlock

from qwenpaw.app.agent_context import scoped_session_id
from qwenpaw.app.routers import loops
from qwenpaw.app.workspace.workspace_plugins import WorkspacePlugins
from qwenpaw.agents.acp.meta import ACP_CONFIG_META_KEY
from qwenpaw.config.config import (
    CustomLoopModeConfig,
    GateInstanceConfig,
    LoopConfig,
)
from qwenpaw.modes.custom_loop import load_custom_loop_modes
from qwenpaw.modes.goal import GoalMode
from qwenpaw.modes.mission import MissionMode
from qwenpaw.modes.catalog import ModeEntry, dispatch_session_command

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
    workspace.plugins.register_mode(MissionMode(), workspace)
    load_custom_loop_modes(workspace)
    return workspace


def _context(agent, text, session_id, workspace, directory):
    parameters = agent._sessions[session_id]
    return SimpleNamespace(
        agent_id=parameters.profile.id,
        agent_config=parameters.config,
        parameters=parameters,
        workspace=workspace,
        session_id=session_id,
        workspace_dir=directory,
        mode_state={},
        input_msgs=[
            Msg(
                name="user",
                role="user",
                content=[TextBlock(type="text", text=text)],
            ),
        ],
    )


@pytest.mark.parametrize(f"method", [f"load_session", f"resume_session"])
async def test_restored_session_does_not_restart_mode(
    method,
    tmp_path,
    monkeypatch,
):
    agent = QwenPawACPAgent(agent_mode=f"goal")
    for name in (
        "_require_mcp",
        f"_cancel_active_prompt",
        f"_cancel_pending_approvals",
        f"_remove_session_mcp",
        f"_sync_session_mcp",
        f"_advertise_commands",
    ):
        monkeypatch.setattr(agent, name, AsyncMock())
    sid = "restored"
    restore = getattr(agent, method)
    await restore(cwd=str(tmp_path), session_id=sid)
    workspace = _workspace()
    task = "Run the new mission"
    with scoped_session_id(sid):
        ctx = _context(agent, "Continue", sid, workspace, tmp_path)
        assert await dispatch_session_command(ctx, "Continue") is None
        assert not workspace.plugins.active_mode_names(ctx)
        assert workspace.plugins.session_modes[sid] == ModeEntry("goal")

        goal = next(
            mode for mode in workspace.plugins.modes if mode.name == "goal"
        )
        assert await dispatch_session_command(ctx, "/goal Finish this") is None
        assert workspace.plugins.active_mode_names(ctx) == {"goal"}
        await restore(
            cwd=str(tmp_path),
            session_id=sid,
            **{ACP_CONFIG_META_KEY: {"agent_mode": "mission"}},
        )
        ctx = _context(agent, task, sid, workspace, tmp_path)
        rejected = await dispatch_session_command(ctx, task)
        assert "End the active goal mode" in rejected.content[0].text
        retry = ModeEntry("mission", retry=True)
        assert workspace.plugins.session_modes[sid] == retry

        await dispatch_session_command(ctx, "/help")
        assert workspace.plugins.session_modes[sid] == retry
        await goal.on_conversation_reset(ctx)
        await restore(cwd=str(tmp_path), session_id=sid)
        ctx = _context(agent, task, sid, workspace, tmp_path)
        assert await dispatch_session_command(ctx, task) is None
        assert workspace.plugins.session_modes[sid] == ModeEntry("mission")
        assert workspace.plugins.active_mode_names(ctx) == {"mission"}
        active_mission = ctx.mode_state["mission"]
        assert await dispatch_session_command(ctx, "Continue") is None
        assert ctx.mode_state["mission"] == active_mission


async def test_workspace_failure_does_not_consume_mode(monkeypatch, tmp_path):
    """Retrying initialization must still activate the requested mode."""
    agent = QwenPawACPAgent(agent_mode=f"goal")

    async def fail():
        raise OSError(f"Temporary workspace failure")

    monkeypatch.setattr(agent, "_require_mcp", AsyncMock())
    monkeypatch.setattr(agent, "_advertise_commands", AsyncMock())
    monkeypatch.setattr(agent, f"_ensure_workspace", fail)
    monkeypatch.setattr(agent, f"_report_prompt_error", AsyncMock())
    session = await agent.new_session(cwd=str(tmp_path))
    with pytest.raises(RequestError):
        await agent.prompt([text_block("Solve")], session.session_id)
    workspace = _workspace()
    ctx = _context(agent, "Solve", session.session_id, workspace, tmp_path)
    with scoped_session_id(session.session_id):
        assert await dispatch_session_command(ctx, "Solve") is None
        assert workspace.plugins.active_mode_names(ctx) == {"goal"}


async def test_custom_mode_uses_shared_catalog_and_existing_dispatch(
    monkeypatch,
    tmp_path,
):
    """A mode ID differing from its command works through HTTP and ACP."""
    config = CustomLoopModeConfig(
        id=f"quality-id",
        name=f"Quality",
        enabled=False,
        slash_command=f"verify",
        gates=[GateInstanceConfig(id=f"limit", type=f"iteration")],
    )
    workspace = _workspace([config])
    agent = QwenPawACPAgent(agent_mode=f"custom:quality-id")
    monkeypatch.setattr(agent, "_require_mcp", AsyncMock())
    monkeypatch.setattr(agent, "_advertise_commands", AsyncMock())
    session = await agent.new_session(cwd=str(tmp_path))
    task = "Check the result"
    with pytest.raises(ValueError):
        await dispatch_session_command(
            _context(agent, task, session.session_id, workspace, tmp_path),
            task,
        )
    config.enabled = True
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

    ctx = _context(agent, task, session.session_id, workspace, tmp_path)
    with scoped_session_id(ctx.session_id):
        result = await dispatch_session_command(ctx, task)
        assert result is None
        assert workspace.plugins.active_mode_names(ctx) == {selected.id}
        assert any(reg.is_active() for reg in workspace.plugins.stop_handlers)
        assert ctx.input_msgs[0].content[0].text == task
        assert await dispatch_session_command(ctx, "Continue") is None
        assert workspace.plugins.session_modes[ctx.session_id] == ModeEntry(
            selected.id,
        )

    explicit = await agent.new_session(cwd=str(tmp_path))
    ctx = _context(agent, "/new", explicit.session_id, workspace, tmp_path)
    with scoped_session_id(explicit.session_id):
        assert await dispatch_session_command(ctx, "/new") is None
        assert ctx.input_msgs[0].content[0].text == "/new"
        assert workspace.plugins.session_modes[ctx.session_id] == ModeEntry(
            selected.id,
        )
        ctx = _context(agent, task, explicit.session_id, workspace, tmp_path)
        assert await dispatch_session_command(ctx, task) is None
        assert not workspace.plugins.active_mode_names(ctx)
