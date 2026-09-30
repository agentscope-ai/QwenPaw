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

import qwenpaw.runtime as runtime_module
from qwenpaw.app.workspace.workspace import Workspace


class FakeHarnessRuntime:
    """Record the routing inputs received from a workspace."""

    def __init__(self) -> None:
        self.call: dict[str, Any] | None = None

    async def stream(self, **kwargs: Any) -> AsyncIterator[str]:
        self.call = kwargs
        yield "harness-output"


@pytest.mark.asyncio
async def test_coding_mode_routes_directly_to_harness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = SimpleNamespace(
        backend="codex",
        coding_mode=SimpleNamespace(enabled=False),
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
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def run(self, _request: object) -> AsyncIterator[str]:
            yield "runtime-output"

    monkeypatch.setattr(runtime_module, "Runtime", FakeRuntime)
    recorder = Mock()
    recorder.start = AsyncMock()
    recorder.observe = AsyncMock()
    recorder.finish = AsyncMock()
    monkeypatch.setattr(
        "qwenpaw.app.workspace.workspace.TranscriptRecorder",
        Mock(return_value=recorder),
    )
    workspace = Workspace("agent-1", str(tmp_path / "workspace"))
    stream = workspace.stream_query(object())

    assert await anext(stream) == "runtime-output"
    await stream.aclose()

    recorder.finish.assert_awaited_once_with("cancelled")
