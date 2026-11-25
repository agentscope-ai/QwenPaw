# -*- coding: utf-8 -*-
"""Tests for workspace routing into a selected third-party agent."""

# pylint: disable=protected-access

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

import qwenpaw.app.workspace.workspace as workspace_module
from qwenpaw._session_signals import (
    TRANSCRIPT_TURN_ID_CONTEXT_KEY,
    TURN_COMMIT_KEY,
)
from qwenpaw.agents.acp.meta import ACP_EPHEMERAL_META_KEY
from qwenpaw.runtime import Runtime as BaseRuntime
from qwenpaw.app.workspace.workspace import Workspace
from qwenpaw.app.chats.session import DatabaseSession
from qwenpaw.app.chats.transcript_catalog import (
    TranscriptCatalog,
    resolve_session_database_path,
)
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


def _turn_state(
    workspace_dir: Path,
    *,
    session_id: str,
    user_id: str,
    channel: str,
) -> tuple[str, int]:
    path = resolve_session_database_path(
        workspace_dir,
        session_id=session_id,
        user_id=user_id,
        channel=channel,
    )
    assert path is not None
    with sqlite3.connect(path) as connection:
        status = connection.execute(
            "SELECT status FROM transcript_turns",
        ).fetchone()[0]
        revisions = connection.execute(
            "SELECT COUNT(*) FROM context_revisions",
        ).fetchone()[0]
    return str(status), int(revisions)


def _select_backend(
    monkeypatch: pytest.MonkeyPatch,
    backend: str = "qwenpaw",
) -> None:
    monkeypatch.setattr(
        "qwenpaw.app.workspace.workspace.load_agent_config_async",
        AsyncMock(return_value=SimpleNamespace(backend=backend)),
    )


def _persistent_workspace(
    tmp_path: Path,
) -> tuple[Workspace, TranscriptCatalog, DatabaseSession]:
    catalog = TranscriptCatalog(tmp_path)
    session = DatabaseSession(
        catalog=catalog,
        legacy_save_dir=str(tmp_path / "sessions"),
    )
    workspace = Workspace("agent-1", str(tmp_path / "workspace"))
    workspace._service_manager.services.update(
        session=session,
        transcript_store=catalog,
    )
    return workspace, catalog, session


def _session_request(
    *,
    input_text: str | None = None,
    ephemeral: bool = False,
) -> AgentRequest:
    input_messages = []
    if input_text is not None:
        input_messages.append(
            Message(
                role=Role.USER,
                content=[TextContent(text=input_text)],
            ),
        )
    request_context = {ACP_EPHEMERAL_META_KEY: True} if ephemeral else {}
    return AgentRequest(
        session_id="s",
        user_id="u",
        channel="console",
        input=input_messages,
        request_context=request_context,
    )


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
    request = _session_request()

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
    _select_backend(monkeypatch)
    workspace, catalog, session = _persistent_workspace(tmp_path)

    class FakeRuntime:
        normalize_request = staticmethod(BaseRuntime.normalize_request)

        def __init__(self, **_kwargs: object) -> None:
            pass

        async def run(self, request: AgentRequest) -> AsyncIterator[Message]:
            try:
                yield Message(
                    id="partial-response",
                    role=Role.ASSISTANT,
                    status=RunStatus.Completed,
                    content=[TextContent(text="partial")],
                )
            finally:
                state = SimpleNamespace(
                    state_dict=lambda: {
                        "state": {
                            "context": [
                                {"role": "user", "text": "question"},
                                {"role": "assistant", "text": "partial"},
                            ],
                        },
                    },
                )
                await session.save_turn_session_state(
                    session_id=request.session_id,
                    user_id=request.user_id,
                    channel=request.channel,
                    turn_id=request.request_context[
                        TRANSCRIPT_TURN_ID_CONTEXT_KEY
                    ],
                    pending_commit=request.request_context[TURN_COMMIT_KEY],
                    agent=state,
                )

    monkeypatch.setattr(workspace_module, "Runtime", FakeRuntime)
    request = _session_request(input_text="question")
    stream = workspace.stream_query(request)

    response = await anext(stream)
    assert response.content[0].text == "partial"
    await stream.aclose()

    snapshot = catalog.read_turn_context(
        session_id="s",
        user_id="u",
        channel="console",
        turn_id=request.request_context[TRANSCRIPT_TURN_ID_CONTEXT_KEY],
    )
    assert snapshot is not None
    assert snapshot.state["agent"]["state"]["context"][-1] == {
        "role": "assistant",
        "text": "partial",
    }
    page = catalog.get_page(
        session_id="s",
        user_id="u",
        channel="console",
    )
    assert page is not None
    assert [item.content[0].text for item in page.messages] == [
        "question",
        "partial",
    ]
    assert _turn_state(
        tmp_path,
        session_id="s",
        user_id="u",
        channel="console",
    ) == ("cancelled", 1)
    catalog.close()


@pytest.mark.asyncio
async def test_repeated_cancel_keeps_session_registered_until_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _select_backend(monkeypatch)
    workspace, catalog, session = _persistent_workspace(tmp_path)
    save_started = asyncio.Event()
    allow_save = asyncio.Event()

    class FakeRuntime:
        normalize_request = staticmethod(BaseRuntime.normalize_request)

        def __init__(self, **_kwargs: object) -> None:
            pass

        async def run(self, request: AgentRequest) -> AsyncIterator[str]:
            try:
                yield "runtime-output"
            finally:
                save_started.set()
                await allow_save.wait()
                state = SimpleNamespace(
                    state_dict=lambda: {"state": {"context": ["partial"]}},
                )
                await session.save_turn_session_state(
                    session_id=request.session_id,
                    user_id=request.user_id,
                    channel=request.channel,
                    turn_id=request.request_context[
                        TRANSCRIPT_TURN_ID_CONTEXT_KEY
                    ],
                    pending_commit=request.request_context[TURN_COMMIT_KEY],
                    agent=state,
                )

    monkeypatch.setattr(workspace_module, "Runtime", FakeRuntime)
    request = _session_request()
    stream = workspace.stream_query(request)

    assert await anext(stream) == "runtime-output"
    close_task = asyncio.create_task(stream.aclose())
    await asyncio.wait_for(save_started.wait(), 1)
    close_task.cancel()
    close_task.cancel()
    assert workspace.task_tracker._session_tasks

    allow_save.set()
    with pytest.raises(asyncio.CancelledError):
        await close_task

    snapshot = catalog.read_turn_context(
        session_id="s",
        user_id="u",
        channel="console",
        turn_id=request.request_context[TRANSCRIPT_TURN_ID_CONTEXT_KEY],
    )
    assert snapshot is not None
    assert snapshot.state["agent"]["state"]["context"] == ["partial"]
    assert not workspace.task_tracker._session_tasks
    catalog.close()


@pytest.mark.asyncio
async def test_completed_close_preserves_committed_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _select_backend(monkeypatch)
    workspace, catalog, session = _persistent_workspace(tmp_path)
    schedule_checkpoint = AsyncMock()
    monkeypatch.setattr(
        workspace_module.CHECKPOINT_RUNTIME,
        "schedule_auto_snapshot",
        schedule_checkpoint,
    )

    class FakeRuntime:
        normalize_request = staticmethod(BaseRuntime.normalize_request)

        def __init__(self, **_kwargs: object) -> None:
            pass

        async def run(
            self,
            request: AgentRequest,
        ) -> AsyncIterator[AgentResponse]:
            state = SimpleNamespace(
                state_dict=lambda: {"state": {"context": ["complete"]}},
            )
            await session.save_turn_session_state(
                session_id=request.session_id,
                user_id=request.user_id,
                channel=request.channel,
                turn_id=request.request_context[
                    TRANSCRIPT_TURN_ID_CONTEXT_KEY
                ],
                pending_commit=request.request_context[TURN_COMMIT_KEY],
                agent=state,
            )
            request.request_context[TURN_COMMIT_KEY]["checkpoint"] = {
                "session_id": request.session_id,
            }
            yield AgentResponse(
                status=RunStatus.Completed,
                output=[
                    Message(
                        id="answer",
                        role=Role.ASSISTANT,
                        status=RunStatus.Completed,
                        content=[TextContent(text="answer")],
                    ),
                ],
            )

    monkeypatch.setattr(workspace_module, "Runtime", FakeRuntime)
    request = _session_request(input_text="question")
    stream = workspace.stream_query(request)

    response = await anext(stream)
    assert response.status == RunStatus.Completed
    before_close = _turn_state(
        tmp_path,
        session_id="s",
        user_id="u",
        channel="console",
    )
    await stream.aclose()
    after_close = _turn_state(
        tmp_path,
        session_id="s",
        user_id="u",
        channel="console",
    )

    assert before_close == ("completed", 1)
    assert after_close == before_close
    schedule_checkpoint.assert_awaited_once()
    catalog.close()


@pytest.mark.asyncio
async def test_workspace_finalization_failure_is_visible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _select_backend(monkeypatch)
    workspace, catalog, _session = _persistent_workspace(tmp_path)

    class BrokenRuntime:
        normalize_request = staticmethod(BaseRuntime.normalize_request)

        def __init__(self, **_kwargs: object) -> None:
            pass

        async def run(self, _request: AgentRequest) -> AsyncIterator[str]:
            try:
                yield "partial"
            finally:
                raise RuntimeError("close failed")

    monkeypatch.setattr(workspace_module, "Runtime", BrokenRuntime)
    request = _session_request()
    stream = workspace.stream_query(request)

    assert await anext(stream) == "partial"
    with pytest.raises(RuntimeError, match="close failed"):
        await stream.aclose()

    assert _turn_state(
        tmp_path,
        session_id="s",
        user_id="u",
        channel="console",
    ) == ("failed", 0)
    assert not workspace.task_tracker._session_tasks
    catalog.close()
