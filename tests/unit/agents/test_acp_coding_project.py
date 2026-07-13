# -*- coding: utf-8 -*-
"""ACP session metadata for TUI Coding Mode projects."""

from __future__ import annotations

from acp import text_block

from qwenpaw.agents.acp.meta import (
    ACP_CODING_PROJECT_META_KEY,
    ACP_EPHEMERAL_META_KEY,
)
from qwenpaw.agents.acp.server import QwenPawACPAgent


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


async def test_acp_project_metadata_flows_to_request_context(tmp_path):
    project_dir = str(tmp_path)
    workspace = _FakeWorkspace()
    agent = _TestACPAgent(workspace)
    agent.on_connect(_FakeConn())

    response = await agent.new_session(
        cwd=project_dir,
        **{ACP_CODING_PROJECT_META_KEY: project_dir},
    )

    await agent.prompt(
        prompt=[text_block("hello")],
        session_id=response.session_id,
    )

    assert workspace.requests
    assert (
        workspace.requests[0].request_context[ACP_CODING_PROJECT_META_KEY]
        == project_dir
    )


async def test_acp_project_metadata_is_stripped(tmp_path):
    project_dir = str(tmp_path)
    workspace = _FakeWorkspace()
    agent = _TestACPAgent(workspace)
    agent.on_connect(_FakeConn())

    response = await agent.new_session(
        cwd=project_dir,
        **{ACP_CODING_PROJECT_META_KEY: f"  {project_dir}  "},
    )

    await agent.prompt(
        prompt=[text_block("hello")],
        session_id=response.session_id,
    )

    assert (
        workspace.requests[0].request_context[ACP_CODING_PROJECT_META_KEY]
        == project_dir
    )


async def test_acp_resume_project_metadata_is_stripped(tmp_path):
    project_dir = str(tmp_path)
    workspace = _FakeWorkspace()
    agent = _TestACPAgent(workspace)
    agent.on_connect(_FakeConn())

    response = await agent.new_session(cwd=project_dir)
    await agent.resume_session(
        cwd=project_dir,
        session_id=response.session_id,
        **{ACP_CODING_PROJECT_META_KEY: f"  {project_dir}  "},
    )

    await agent.prompt(
        prompt=[text_block("hello")],
        session_id=response.session_id,
    )

    assert (
        workspace.requests[0].request_context[ACP_CODING_PROJECT_META_KEY]
        == project_dir
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
