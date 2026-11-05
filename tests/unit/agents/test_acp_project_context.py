# -*- coding: utf-8 -*-
"""ACP session configuration and project context."""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from acp import RequestError, text_block
from agentscope.agent import ReActConfig

from qwenpaw.agents.acp.meta import (
    ACP_EPHEMERAL_META_KEY,
    ACP_CONFIG_META_KEY,
    ACP_PROJECT_DIR_META_KEY,
)
from qwenpaw.agents.acp.server import QwenPawACPAgent
from qwenpaw.app.agent_context import scoped_session_id
from qwenpaw.app.workspace import Workspace
from qwenpaw.config.config import (
    AgentProfileConfig,
    ModelSlotConfig,
    load_agent_config,
)
from qwenpaw.modes.default import DefaultMode, resolve_max_iterations
from qwenpaw.runtime.builder import _resolve_react_iterations
from qwenpaw.runtime.tool_guard import _guarded_tool_resolve_execution_level
from qwenpaw.security.tool_guard.execution_level import ToolExecutionLevel
from qwenpaw.services.project_directory import (
    agent_project_dirs_from_config,
    resolve_effective_project_dirs,
)
from qwenpaw.utils.io_utils import run_sync_io


class _FakeConn:
    async def session_update(self, session_id, update):  # noqa: ANN001
        del session_id, update
        return None


class _FakeWorkspace:
    def __init__(self) -> None:
        self.requests = []
        self.configs = []
        self.approval_levels = []

    async def stream_query(self, request):  # noqa: ANN001
        self.requests.append(request)
        config = load_agent_config(request.agent_id)
        self.configs.append(config)
        self.approval_levels.append(
            _guarded_tool_resolve_execution_level(
                SimpleNamespace(_qp_agent_id=request.agent_id),
            ),
        )
        await asyncio.sleep(0)
        thread_config = await run_sync_io(load_agent_config, request.agent_id)
        assert config == thread_config
        for event in ():
            yield event


class _TestACPAgent(QwenPawACPAgent):
    def __init__(self, workspace: _FakeWorkspace, **kwargs) -> None:
        super().__init__(agent_id="default", **kwargs)
        self._fake_workspace = workspace

    async def _ensure_workspace(self):
        return self._fake_workspace


async def test_acp_config_precedence_and_instance_isolation(
    tmp_path,
    monkeypatch,
):
    workspace = _FakeWorkspace()
    base = load_agent_config("default")
    agent = _TestACPAgent(
        workspace,
        config_overrides={
            "running": {"shell_command_timeout": 41},
            "system_prompt_files": ["AGENTS.md"],
            "thinking_level": "budget",
            "thinking_budget": 4096,
        },
    )
    other = _TestACPAgent(workspace)
    agent.on_connect(_FakeConn())
    other.on_connect(_FakeConn())
    first = await agent.new_session(
        cwd=str(tmp_path),
        **{
            ACP_CONFIG_META_KEY: {
                "running": {"shell_command_timeout": 17},
                "system_prompt_files": [],
                "thinking_level": "off",
                "thinking_budget": None,
                "coding_mode": {"enabled": False},
            },
        },
    )
    second = await agent.new_session(cwd=str(tmp_path))
    third = await other.new_session(cwd=str(tmp_path))
    await asyncio.gather(
        agent.prompt([text_block("one")], first.session_id),
        agent.prompt([text_block("two")], second.session_id),
        other.prompt([text_block("three")], third.session_id),
    )
    configs = {
        request.session_id: config
        for request, config in zip(workspace.requests, workspace.configs)
    }
    first_config = configs[first.session_id]
    assert first_config.running.shell_command_timeout == 17
    assert first_config.system_prompt_files == []
    assert first_config.thinking_budget is None
    assert first_config.coding_mode.enabled is False
    assert configs[second.session_id].running.shell_command_timeout == 41
    assert configs[second.session_id].system_prompt_files == ["AGENTS.md"]
    assert configs[third.session_id].running == base.running
    assert load_agent_config("default") == base
    with pytest.raises(RequestError, match="Invalid params"):
        await agent.resume_session(
            cwd=str(tmp_path),
            session_id=first.session_id,
            **{ACP_CONFIG_META_KEY: {"workspace_dir": str(tmp_path)}},
        )
    assert agent._sessions[first.session_id].config == first_config
    selected = ModelSlotConfig(provider_id="test", model="session-model")
    monkeypatch.setattr(
        agent,
        "_switch_model",
        AsyncMock(return_value=selected),
    )
    await agent.set_session_model("test:session-model", first.session_id)
    assert agent._sessions[first.session_id].config.active_model == selected
    assert (
        agent._sessions[second.session_id].config.active_model
        == base.active_model
    )
    assert first_config.active_model == base.active_model
    assert load_agent_config("default") == base
    await agent.set_config_option(
        "mode",
        first.session_id,
        "bypassPermissions",
    )
    await agent.prompt([text_block("bypass")], first.session_id)
    await agent.prompt([text_block("default")], second.session_id)
    assert workspace.approval_levels[-2] == ToolExecutionLevel.OFF.value
    assert workspace.approval_levels[-1] == (
        ToolExecutionLevel.from_config(base.approval_level).value
    )
    await agent.set_config_option("mode", first.session_id, "default")
    await agent.prompt([text_block("restored")], first.session_id)
    assert workspace.approval_levels[-1] == workspace.approval_levels[-2]
    assert agent._sessions[first.session_id].config.active_model == selected


async def test_acp_project_config_preserves_legacy_restore_contract(tmp_path):
    agent = _TestACPAgent(_FakeWorkspace())
    session = await agent.new_session(
        cwd="original",
        **{
            ACP_PROJECT_DIR_META_KEY: "legacy",
            ACP_CONFIG_META_KEY: {"project_dir": "configured"},
        },
    )
    await agent.resume_session(cwd="changed", session_id=session.session_id)
    assert agent._sessions[session.session_id].config.project_dir == "legacy"
    await agent.resume_session(
        cwd="changed",
        session_id=session.session_id,
        **{ACP_PROJECT_DIR_META_KEY: "updated"},
    )
    assert agent._sessions[session.session_id].config.project_dirs == [
        {"path": "updated"},
    ]
    directories = [{"path": str(tmp_path), "access": "read_write"}]
    await agent.resume_session(
        cwd="ignored",
        session_id=session.session_id,
        **{ACP_CONFIG_META_KEY: {"project_dirs": directories}},
    )
    info = agent._sessions[session.session_id]
    assert info.config.project_dir is None
    assert info.config.project_dirs == directories
    await agent.load_session(
        cwd="old-client",
        session_id=session.session_id,
        **{ACP_CONFIG_META_KEY: {}},
    )
    assert (
        agent._sessions[session.session_id].config.project_dir == "old-client"
    )


async def test_acp_close_releases_only_its_session_gate_state(tmp_path):
    mode = DefaultMode()
    agent = _TestACPAgent(_FakeWorkspace())
    sessions = [await agent.new_session(cwd=str(tmp_path)) for _ in range(2)]
    for session in sessions:
        with scoped_session_id(session.session_id):
            await mode.on_turn_start(
                SimpleNamespace(
                    agent_config=agent._sessions[session.session_id].config,
                ),
            )
    workspace = object.__new__(Workspace)
    workspace.agent_id = "default"
    workspace.workspace_dir = tmp_path
    workspace._app_services = None
    workspace.plugins = SimpleNamespace(modes=[mode])
    agent._workspace = workspace
    await agent.close_session(sessions[0].session_id)
    assert set(mode._handlers) == {sessions[1].session_id}
    assert set(mode._config_keys) == {sessions[1].session_id}


async def test_acp_project_dir_is_normalized_into_configuration(tmp_path):
    project_dir = str(tmp_path)
    workspace = _FakeWorkspace()
    agent = _TestACPAgent(workspace)
    agent.on_connect(_FakeConn())

    response = await agent.new_session(
        cwd=project_dir,
        **{ACP_PROJECT_DIR_META_KEY: project_dir},
    )

    await agent.prompt(
        prompt=[text_block("hello")],
        session_id=response.session_id,
    )

    assert workspace.requests
    assert workspace.configs[0].project_dir == project_dir
    config = workspace.configs[0]
    resolved = resolve_effective_project_dirs(
        tmp_path,
        agent_project_dirs=agent_project_dirs_from_config(config),
    )
    assert resolved.primary.path == tmp_path
    assert "project_dir" not in workspace.requests[0].request_context


async def test_acp_project_dir_preserves_trailing_space(tmp_path):
    project_dir = str(tmp_path)
    provided_project_dir = f"{project_dir} "
    workspace = _FakeWorkspace()
    agent = _TestACPAgent(workspace)
    agent.on_connect(_FakeConn())

    response = await agent.new_session(
        cwd=project_dir,
        **{ACP_PROJECT_DIR_META_KEY: provided_project_dir},
    )

    await agent.prompt(
        prompt=[text_block("hello")],
        session_id=response.session_id,
    )

    assert workspace.configs[0].project_dir == provided_project_dir


async def test_acp_resume_project_dir_preserves_trailing_space(tmp_path):
    project_dir = str(tmp_path)
    provided_project_dir = f"{project_dir} "
    workspace = _FakeWorkspace()
    agent = _TestACPAgent(workspace)
    agent.on_connect(_FakeConn())

    response = await agent.new_session(cwd=project_dir)
    await agent.resume_session(
        cwd=project_dir,
        session_id=response.session_id,
        **{ACP_PROJECT_DIR_META_KEY: provided_project_dir},
    )

    await agent.prompt(
        prompt=[text_block("hello")],
        session_id=response.session_id,
    )

    assert workspace.configs[0].project_dir == provided_project_dir


async def test_acp_ephemeral_metadata_is_normalized_into_configuration(
    tmp_path,
):
    project_dir = str(tmp_path)
    workspace = _FakeWorkspace()
    agent = _TestACPAgent(workspace)
    agent.on_connect(_FakeConn())

    response = await agent.new_session(
        cwd=project_dir,
        **{ACP_EPHEMERAL_META_KEY: True},
    )

    await agent.prompt(
        prompt=[text_block("warmup")],
        session_id=response.session_id,
    )

    assert workspace.requests
    assert workspace.configs[0].session_persistence is False
    assert "ephemeral" not in workspace.requests[0].request_context


@pytest.mark.parametrize("enabled", [True, False])
async def test_acp_loop_budget_is_private_and_reaches_react(tmp_path, enabled):
    workspace = _FakeWorkspace()
    agent = _TestACPAgent(workspace)
    agent.on_connect(_FakeConn())
    loop = {"iteration": {"enabled": enabled, "max_iterations": 10000}}
    first = await agent.new_session(
        cwd=str(tmp_path),
        **{ACP_CONFIG_META_KEY: {"running": {"loop": loop}}},
    )
    second = await agent.new_session(cwd=str(tmp_path))
    await asyncio.gather(
        *(
            agent.prompt(
                prompt=[text_block("hello")],
                session_id=session.session_id,
            )
            for session in (first, second)
        ),
    )
    assert resolve_max_iterations(workspace.configs[1].running) == 100
    original = AgentProfileConfig(id="default", name="Default")
    before = original.model_dump()
    assert original.running.loop.iteration.enabled is True
    assert resolve_max_iterations(original.running) == 100
    configured = workspace.configs[0]
    assert original.model_dump() == before
    assert configured.running.loop.doom_loop == original.running.loop.doom_loop
    limit = resolve_max_iterations(configured.running)
    assert limit == (10000 if enabled else None)
    react = ReActConfig(max_iters=_resolve_react_iterations(limit, {}))
    assert react.max_iters == (10000 if enabled else sys.maxsize)


@pytest.mark.parametrize("method", ["load_session", "resume_session"])
async def test_acp_loop_survives_restore_and_can_be_replaced(tmp_path, method):
    workspace = _FakeWorkspace()
    agent = _TestACPAgent(workspace)
    agent.on_connect(_FakeConn())
    loop = {"iteration": {"enabled": True, "max_iterations": 10000}}
    session = await agent.new_session(
        cwd=str(tmp_path),
        **{ACP_CONFIG_META_KEY: {"running": {"loop": loop}}},
    )
    restore = getattr(agent, method)
    await restore(cwd=str(tmp_path), session_id=session.session_id)
    with pytest.raises(RequestError):
        await restore(
            cwd=str(tmp_path),
            session_id=session.session_id,
            **{ACP_CONFIG_META_KEY: {"running": {"max_iters": 0}}},
        )
    await agent.prompt(
        prompt=[text_block("continue")],
        session_id=session.session_id,
    )
    assert resolve_max_iterations(workspace.configs[-1].running) == 10000
    await restore(
        cwd=str(tmp_path),
        session_id=session.session_id,
        **{ACP_CONFIG_META_KEY: {}},
    )
    await agent.prompt(
        prompt=[text_block("continue")],
        session_id=session.session_id,
    )
    assert resolve_max_iterations(workspace.configs[-1].running) == 100


@pytest.mark.parametrize(
    "loop",
    [
        None,
        {"iteration": {"max_iterations": 0}},
        {"iteration": {"max_iterations": True}},
        {"iteration": {"max_iterations": "10000"}},
        {"iteration": {"max_iters": 10000}},
        {"doom_loop": {"stages": [{"after": 3, "unknown": True}]}},
        {"unsupported": {}},
    ],
)
async def test_acp_invalid_loop_does_not_create_session(tmp_path, loop):
    agent = _TestACPAgent(_FakeWorkspace())
    with pytest.raises(RequestError):
        await agent.new_session(
            cwd=str(tmp_path),
            **{ACP_CONFIG_META_KEY: {"running": {"loop": loop}}},
        )
    assert not agent._sessions  # pylint: disable=protected-access
