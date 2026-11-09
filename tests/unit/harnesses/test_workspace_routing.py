# -*- coding: utf-8 -*-
"""Tests for workspace routing into a selected third-party agent."""

# pylint: disable=protected-access

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from qwenpaw.app.crons.models import CronJobRequest
from qwenpaw.app.workspace.workspace import Workspace
from qwenpaw.harnesses.events import HarnessAttachmentKind
from qwenpaw.harnesses.runtime import HarnessRuntime
from qwenpaw.schemas import AgentRequest


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
    request = object()

    output = [item async for item in workspace.stream_query(request)]

    assert output == ["harness-output"]
    assert runtime.call == {
        "backend": "codex",
        "request": request,
        "cwd": (tmp_path / "workspace").resolve(),
        "settings": {
            "_request_context": {
                "agent_id": "agent-1",
                "session_id": None,
                "user_id": None,
                "channel": "console",
            },
        },
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
    monkeypatch.setattr(
        "qwenpaw.app.workspace.workspace.load_agent_config",
        lambda _agent_id: SimpleNamespace(backend=backend),
    )
    workspace = Workspace("agent-1", str(tmp_path / "workspace"))
    runtime = FakeHarnessRuntime()
    workspace._harness_runtime = runtime
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
    prompt, attachments = HarnessRuntime._content_from_request(forwarded)
    assert prompt == "Summarize yesterday's usage."
    assert len(attachments) == 1
    assert attachments[0].kind == HarnessAttachmentKind.FILE
    assert attachments[0].path == attachment
    assert runtime.call["settings"]["_request_context"] == {
        "agent_id": "agent-1",
        "session_id": "cron-session",
        "user_id": "cron-user",
        "channel": "dingtalk",
        "source": "cron",
        "cron_job_id": "job-1",
        "approval_level": "off",
    }
    if not as_dict:
        assert forwarded is request


@pytest.mark.asyncio
@pytest.mark.parametrize("as_dict", [True, False])
async def test_portability_adaptation_cannot_route_to_harness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    as_dict: bool,
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
    if as_dict:
        request = vars(request)

    with pytest.raises(PermissionError, match="PawPort compatibility"):
        _ = [item async for item in workspace.stream_query(request)]

    assert runtime.call is None
