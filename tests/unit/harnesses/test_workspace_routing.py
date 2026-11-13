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
from qwenpaw.runtime.backends.session import HarnessSessionBridge
from qwenpaw.schemas import (
    AgentRequest,
    AgentResponse,
    Message,
    Role,
    RunStatus,
    TextContent,
)
from qwenpaw.app.crons.models import CronJobRequest
from qwenpaw.plugins.harnesses import HarnessAttachmentKind
from qwenpaw.runtime.backends.execution import BackendExecution


class FakeBackendRuntime:
    """Record the generic runtime inputs received from a workspace."""

    def __init__(self) -> None:
        self.call: dict[str, Any] | None = None

    async def stream(
        self,
        backend: str,
        request: Any,
        settings: dict,
        *,
        cwd: Path,
    ) -> AsyncIterator[str]:
        self.call = {
            "backend": backend,
            "request": request,
            "settings": settings,
            "cwd": cwd,
        }
        yield "harness-output"


@pytest.mark.asyncio
async def test_selected_backend_routes_directly_to_harness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = SimpleNamespace(
        backend="codex",
    )

    async def load(_agent_id):
        return config

    monkeypatch.setattr(
        "qwenpaw.app.workspace.workspace.load_agent_config_async",
        load,
    )
    workspace = Workspace("agent-1", str(tmp_path / "workspace"))
    runtime = FakeBackendRuntime()
    workspace._backend_runtime = runtime
    request = SimpleNamespace(request_context={})

    output = [item async for item in workspace.stream_query(request)]

    assert output == ["harness-output"]
    assert runtime.call == {
        "backend": "codex",
        "request": request,
        "cwd": (tmp_path / "workspace").resolve(),
        "settings": {},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["codex", "qoder"])
@pytest.mark.parametrize("as_dict", [True, False])
async def test_cron_request_preserves_content_and_context_for_harness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    backend: str,
    as_dict: bool,
) -> None:
    async def load(_agent_id):
        return SimpleNamespace(backend=backend)

    monkeypatch.setattr(
        "qwenpaw.app.workspace.workspace.load_agent_config_async",
        load,
    )
    workspace = Workspace("agent-1", str(tmp_path / "workspace"))
    runtime = FakeBackendRuntime()
    workspace._backend_runtime = runtime
    attachment = tmp_path / "report.csv"
    request = CronJobRequest(
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Summarize yesterday's usage."},
                    {"type": "file", "file_url": str(attachment)},
                ],
            },
        ],
        session_id="cron-session",
        user_id="cron-user",
        channel="dingtalk",
        request_context={
            "source": "cron",
            "cron_job_id": "job-1",
            "approval_level": "off",
        },
    ).model_dump(mode="json")
    if not as_dict:
        request = AgentRequest(**request)

    output = [item async for item in workspace.stream_query(request)]

    assert output == ["harness-output"]
    assert runtime.call is not None
    forwarded = runtime.call["request"]
    prompt, attachments = BackendExecution._content_from_request(forwarded)
    assert prompt == "Summarize yesterday's usage."
    assert len(attachments) == 1
    assert attachments[0].kind == HarnessAttachmentKind.FILE
    assert attachments[0].path == attachment
    assert runtime.call["backend"] == backend
    assert runtime.call["cwd"] == (tmp_path / "workspace").resolve()
    assert runtime.call["settings"] == {}
    assert workspace.agent_id == "agent-1"
    assert forwarded.session_id == "cron-session"
    assert forwarded.user_id == "cron-user"
    assert forwarded.channel == "dingtalk"
    assert {
        key: value
        for key, value in forwarded.request_context.items()
        if not key.startswith("_qwenpaw_")
    } == {
        "source": "cron",
        "cron_job_id": "job-1",
        "approval_level": "off",
    }
    if as_dict:
        assert isinstance(forwarded, AgentRequest)
        assert forwarded is not request
    else:
        assert forwarded is request


@pytest.mark.asyncio
@pytest.mark.parametrize("as_dict", [True, False])
async def test_portability_adaptation_cannot_route_to_harness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    as_dict: bool,
) -> None:
    async def load(_agent_id):
        return SimpleNamespace(backend="codex")

    monkeypatch.setattr(
        "qwenpaw.app.workspace.workspace.load_agent_config_async",
        load,
    )
    workspace = Workspace("agent-1", str(tmp_path / "workspace"))
    runtime = FakeBackendRuntime()
    workspace._backend_runtime = runtime
    request = SimpleNamespace(
        request_context={"source": "portability_adaptation"},
        session_id="migration-worker",
        user_id="migration-worker",
        channel="console",
    )
    if as_dict:
        request = vars(request)

    with pytest.raises(PermissionError, match="PawPort compatibility"):
        _ = [item async for item in workspace.stream_query(request)]

    assert runtime.call is None


@pytest.mark.asyncio
async def test_closing_qwenpaw_stream_finishes_cancelled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "qwenpaw.app.workspace.workspace.load_agent_config_async",
        AsyncMock(return_value=SimpleNamespace(backend="qwenpaw")),
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
        "qwenpaw.app.workspace.workspace.load_agent_config_async",
        AsyncMock(return_value=SimpleNamespace(backend="codex")),
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
        async def stream(self, backend, request, settings, **kwargs):
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

    workspace._backend_runtime = Runtime()
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
