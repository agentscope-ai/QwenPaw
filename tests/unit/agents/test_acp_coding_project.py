# -*- coding: utf-8 -*-
"""ACP session metadata for TUI Coding Mode projects."""

from __future__ import annotations

from acp import text_block

from qwenpaw.agents.acp.meta import ACP_CODING_PROJECT_META_KEY
from qwenpaw.agents.acp.server import QwenPawACPAgent


class _FakeConn:
    async def session_update(self, session_id, update):  # noqa: ANN001
        return None


class _FakeWorkspace:
    def __init__(self) -> None:
        self.requests = []

    async def stream_query(self, request):  # noqa: ANN001
        self.requests.append(request)
        if False:
            yield None


async def test_acp_project_metadata_flows_to_request_context(tmp_path):
    project_dir = str(tmp_path)
    agent = QwenPawACPAgent(agent_id="default")
    workspace = _FakeWorkspace()
    agent._workspace = workspace
    agent._workspace_ready = True
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
    assert workspace.requests[0].request_context[
        ACP_CODING_PROJECT_META_KEY
    ] == project_dir
