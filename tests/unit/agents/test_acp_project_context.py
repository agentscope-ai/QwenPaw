# -*- coding: utf-8 -*-
"""ACP session project and loop context metadata."""

from __future__ import annotations

import sys

import pytest
from acp import RequestError, text_block
from agentscope.agent import ReActConfig

from qwenpaw.agents.acp.meta import (
    ACP_EPHEMERAL_META_KEY,
    ACP_LOOP_META_KEY,
    ACP_PROJECT_DIR_META_KEY,
)
from qwenpaw.agents.acp.server import QwenPawACPAgent
from qwenpaw.config.config import AgentProfileConfig
from qwenpaw.config.session_loop import apply_session_loop
from qwenpaw.modes.default import resolve_max_iterations
from qwenpaw.runtime.builder import _resolve_react_iterations


class _FakeConn:
    async def session_update(self, session_id, update):  # noqa: ANN001
        del session_id, update
        return None


class _FakeWorkspace:
    def __init__(self) -> None:
        self.requests = []

    async def stream_query(self, request):  # noqa: ANN001
        self.requests.append(request)
        for event in ():
            yield event


class _TestACPAgent(QwenPawACPAgent):
    def __init__(self, workspace: _FakeWorkspace) -> None:
        super().__init__(agent_id="default")
        self._fake_workspace = workspace

    async def _ensure_workspace(self):
        return self._fake_workspace


async def test_acp_project_dir_flows_to_request_context(tmp_path):
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
    assert workspace.requests[0].request_context["project_dir"] == project_dir


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

    assert (
        workspace.requests[0].request_context["project_dir"]
        == provided_project_dir
    )


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

    assert (
        workspace.requests[0].request_context["project_dir"]
        == provided_project_dir
    )


async def test_acp_ephemeral_metadata_flows_to_request_context(tmp_path):
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
    assert (
        workspace.requests[0].request_context[ACP_EPHEMERAL_META_KEY] is True
    )


@pytest.mark.parametrize("enabled", [True, False])
async def test_acp_loop_budget_is_private_and_reaches_react(tmp_path, enabled):
    workspace = _FakeWorkspace()
    agent = _TestACPAgent(workspace)
    agent.on_connect(_FakeConn())
    loop = {"iteration": {"enabled": enabled, "max_iterations": 10000}}
    first = await agent.new_session(
        cwd=str(tmp_path), **{ACP_LOOP_META_KEY: loop},
    )
    second = await agent.new_session(cwd=str(tmp_path))
    for session in (first, second):
        await agent.prompt(
            prompt=[text_block("hello")], session_id=session.session_id,
        )
    context = workspace.requests[0].request_context
    assert context[ACP_LOOP_META_KEY] == loop
    assert ACP_LOOP_META_KEY not in workspace.requests[1].request_context
    original = AgentProfileConfig(id="default", name="Default")
    before = original.model_dump()
    assert original.running.loop.iteration.enabled is True
    assert resolve_max_iterations(original.running) == 100
    configured = apply_session_loop(original, context[ACP_LOOP_META_KEY])
    assert original.model_dump() == before
    assert (
        configured.running.loop.doom_loop == original.running.loop.doom_loop
    )
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
        cwd=str(tmp_path), **{ACP_LOOP_META_KEY: loop},
    )
    restore = getattr(agent, method)
    await restore(cwd=str(tmp_path), session_id=session.session_id)
    with pytest.raises(RequestError):
        await restore(
            cwd=str(tmp_path), session_id=session.session_id,
            **{ACP_LOOP_META_KEY: {"iteration": {"max_iterations": 0}}},
        )
    await agent.prompt(
        prompt=[text_block("continue")], session_id=session.session_id,
    )
    assert workspace.requests[-1].request_context[ACP_LOOP_META_KEY] == loop
    await restore(
        cwd=str(tmp_path), session_id=session.session_id,
        **{ACP_LOOP_META_KEY: {}},
    )
    await agent.prompt(
        prompt=[text_block("continue")], session_id=session.session_id,
    )
    assert workspace.requests[-1].request_context[ACP_LOOP_META_KEY] == {}


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
            cwd=str(tmp_path), **{ACP_LOOP_META_KEY: loop},
        )
    assert not agent._sessions  # pylint: disable=protected-access
