# -*- coding: utf-8 -*-
"""Tests for workspace routing into a selected third-party agent."""

# pylint: disable=protected-access

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from qwenpaw.app.workspace.workspace import Workspace


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
    request = object()

    output = [item async for item in workspace.stream_query(request)]

    assert output == ["harness-output"]
    assert runtime.call == {
        "backend": "codex",
        "request": request,
        "cwd": (tmp_path / "workspace").resolve(),
        "settings": {},
    }


@pytest.mark.asyncio
async def test_portability_adaptation_cannot_route_to_harness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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

    with pytest.raises(PermissionError, match="PawPort compatibility"):
        _ = [item async for item in workspace.stream_query(request)]

    assert runtime.call is None
