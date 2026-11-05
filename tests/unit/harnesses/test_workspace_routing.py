# -*- coding: utf-8 -*-
"""Tests for workspace routing into a selected third-party agent."""

# pylint: disable=protected-access

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

import qwenpaw.app.workspace.workspace as workspace_module
from qwenpaw.runtime import Runtime as BaseRuntime
from qwenpaw.app.workspace.workspace import Workspace
from qwenpaw.app.chats.session import DatabaseSession
from qwenpaw.app.chats.transcript_catalog import TranscriptCatalog
from qwenpaw.harnesses.session import HarnessSessionBridge
from qwenpaw.schemas import (
    AgentRequest,
    AgentResponse,
    Message,
    Role,
    RunStatus,
    TextContent,
)


class FakeHarnessRuntime:
    """Record the routing inputs received from a workspace."""

    def __init__(self) -> None:
        self.call: dict[str, Any] | None = None

    async def stream(self, **kwargs: Any) -> AsyncIterator[str]:
        self.call = kwargs
        yield "harness-output"


@pytest.mark.asyncio
async def test_selected_backend_routes_directly_to_harness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = SimpleNamespace(
        backend="codex",
    )
    monkeypatch.setattr(
        "qwenpaw.app.workspace.workspace.load_agent_config",
        lambda _agent_id: config,
    )
    workspace = Workspace("agent-1", str(tmp_path / "workspace"))
    runtime = FakeHarnessRuntime()
    workspace._harness_runtime = runtime
    request = SimpleNamespace(request_context={})

    output = [item async for item in workspace.stream_query(request)]

    assert output == ["harness-output"]
    assert runtime.call == {
        "backend": "codex",
        "request": request,
        "cwd": (tmp_path / "workspace").resolve(),
        "settings": {
            "_request_context": {
                "agent_id": "agent-1",
                "session_id": request.session_id,
                "user_id": request.session_id,
                "channel": "",
            },
        },
    }


@pytest.mark.asyncio
async def test_portability_adaptation_cannot_route_to_harness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "qwenpaw.app.workspace.workspace.load_agent_config",
        lambda _agent_id: SimpleNamespace(backend="codex"),
    )
    workspace = Workspace("agent-1", str(tmp_path / "workspace"))
    runtime = FakeHarnessRuntime()
    workspace._harness_runtime = runtime
    request = SimpleNamespace(
        request_context={"source": "portability_adaptation"},
        session_id="migration-worker",
        user_id="migration-worker",
        channel="console",
    )

    with pytest.raises(PermissionError, match="PawPort compatibility"):
        _ = [item async for item in workspace.stream_query(request)]

    assert runtime.call is None


@pytest.mark.asyncio
async def test_closing_qwenpaw_stream_finishes_cancelled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "qwenpaw.app.workspace.workspace.load_agent_config",
        lambda _agent_id: SimpleNamespace(backend="qwenpaw"),
    )

    class FakeRuntime:
        normalize_request = staticmethod(BaseRuntime.normalize_request)

        def __init__(self, **_kwargs: object) -> None:
            pass

        async def run(self, _request: object) -> AsyncIterator[str]:
            yield "runtime-output"

    monkeypatch.setattr(workspace_module, "Runtime", FakeRuntime)
    recorder = Mock()
    recorder.start = AsyncMock()
    recorder.observe = AsyncMock()
    recorder.finish = AsyncMock()
    monkeypatch.setattr(
        "qwenpaw.app.workspace.workspace.TranscriptRecorder",
        Mock(return_value=recorder),
    )
    workspace = Workspace("agent-1", str(tmp_path / "workspace"))
    stream = workspace.stream_query(AgentRequest())

    assert await anext(stream) == "runtime-output"
    await stream.aclose()

    recorder.finish.assert_awaited_once_with("cancelled")


@pytest.mark.asyncio
async def test_harness_turn_commits_forkable_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "qwenpaw.app.workspace.workspace.load_agent_config",
        lambda _: SimpleNamespace(backend="codex"),
    )
    workspace = Workspace("agent-1", str(tmp_path))
    catalog = TranscriptCatalog(tmp_path)
    session = DatabaseSession(
        catalog=catalog,
        legacy_save_dir=str(tmp_path / "sessions"),
    )
    workspace._service_manager.services.update(
        session=session,
        transcript_store=catalog,
    )
    bridge = HarnessSessionBridge(session)

    class Runtime:
        async def stream(self, *, request, **kwargs):
            response = AgentResponse(
                id="response",
                status=RunStatus.Completed,
                output=[
                    Message(
                        role=Role.ASSISTANT,
                        status=RunStatus.Completed,
                        content=[TextContent(text="answer")],
                    ),
                ],
            )
            await bridge.append_turn(
                request=request,
                response=response,
                backend="codex",
            )
            yield response

    workspace._harness_runtime = Runtime()
    request = AgentRequest(
        session_id="s",
        user_id="u",
        channel="console",
        input=[
            Message(
                role=Role.USER,
                content=[TextContent(text="question")],
            ),
        ],
    )
    output = [item async for item in workspace.stream_query(request)]
    assert output[-1].status == RunStatus.Completed
    identity = dict(session_id="s", user_id="u", channel="console")
    page = catalog.get_page(**identity)
    assert len(page.messages) == 2
    turn_id = request.request_context["_qwenpaw_transcript_turn_id"]
    assert (
        output[-1].output[0].metadata["qwenpaw_transcript_position"]["turn_id"]
        == turn_id
    )
    snapshot = catalog.read_turn_context(**identity, turn_id=turn_id)
    assert len(snapshot.state["agent"]["state"]["context"]) == 2
    catalog.close()
