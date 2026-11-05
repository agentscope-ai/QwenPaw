# -*- coding: utf-8 -*-
"""Tests for ACP ``--agent-mode`` first-message prefixing."""
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
from qwenpaw.config.config import (
    CustomLoopModeConfig,
    GateInstanceConfig,
    LoopConfig,
)
from qwenpaw.modes.custom_loop import load_custom_loop_modes
from qwenpaw.modes.goal import GoalMode
from qwenpaw.modes.catalog import prepare_session_message

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


def _prepare(agent, text, session_id, workspace):
    parameters = (
        agent._sessions.get(session_id) or agent._session_configuration()
    )
    return prepare_session_message(
        SimpleNamespace(
            agent_config=parameters.config,
            parameters=parameters,
            workspace=workspace,
            session_id=session_id,
        ),
        text,
    )


@pytest.mark.parametrize(f"method", [f"load_session", f"resume_session"])
async def test_restored_session_does_not_restart_mode(
    method,
    tmp_path,
    monkeypatch,
):
    agent = QwenPawACPAgent(agent_mode=f"goal")
    for name in (
        f"_cancel_active_prompt",
        f"_cancel_pending_approvals",
        f"_remove_session_mcp",
        f"_sync_session_mcp",
        f"_advertise_commands",
    ):
        monkeypatch.setattr(agent, name, AsyncMock())
    await getattr(agent, method)(cwd=str(tmp_path), session_id=f"restored")
    assert _prepare(agent, f"Continue", f"restored", _workspace()) == (
        f"Continue"
    )


async def test_workspace_failure_does_not_consume_mode(monkeypatch):
    """Retrying initialization must still activate the requested mode."""
    agent = QwenPawACPAgent(agent_mode=f"goal")

    async def fail():
        raise OSError(f"Temporary workspace failure")

    monkeypatch.setattr(agent, f"_ensure_workspace", fail)
    monkeypatch.setattr(agent, f"_report_prompt_error", AsyncMock())
    with pytest.raises(RequestError):
        await agent.prompt([text_block(f"Solve")], f"retry")
    assert _prepare(agent, f"Solve", f"retry", _workspace()) == f"/goal Solve"


async def test_custom_mode_uses_shared_catalog_and_existing_dispatch(
    monkeypatch,
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
    with pytest.raises(ValueError):
        _prepare(
            agent,
            f"Check the result",
            f"custom-session",
            workspace,
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

    text = _prepare(
        agent,
        f"Check the result",
        f"custom-session",
        workspace,
    )
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
        _prepare(agent, f"Continue", ctx.session_id, workspace) == f"Continue"
    )

    assert _prepare(agent, f"/new", f"explicit", workspace) == f"/new"
    assert _prepare(agent, f"Follow up", f"explicit", workspace) == (
        f"Follow up"
    )
