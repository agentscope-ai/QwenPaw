# -*- coding: utf-8 -*-
"""Tests for Files API project-directory request context."""

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from qwenpaw.app.agent_context import get_project_dir_for_request


def _request(project_dir: Path) -> Request:
    """Build a request carrying a pending Session directory."""
    return Request(
        {
            "type": "http",
            "headers": [
                (
                    b"x-session-project-dir",
                    str(project_dir).encode(),
                ),
            ],
        },
    )


@pytest.mark.asyncio
async def test_pending_session_project_dir_is_used(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use the pending directory before a backend Chat exists."""
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _agent_id: SimpleNamespace(project_dir=None),
    )
    workspace = SimpleNamespace(
        agent_id="default",
        workspace_dir=tmp_path / "workspace",
    )

    result = await get_project_dir_for_request(
        _request(tmp_path),
        workspace,
    )

    assert result == tmp_path.resolve()


@pytest.mark.asyncio
async def test_pending_session_project_dir_must_exist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject an unavailable pending directory."""
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _agent_id: SimpleNamespace(project_dir=None),
    )
    workspace = SimpleNamespace(
        agent_id="default",
        workspace_dir=tmp_path,
    )

    with pytest.raises(HTTPException) as error:
        await get_project_dir_for_request(
            _request(tmp_path / "missing"),
            workspace,
        )

    assert error.value.status_code == 400


@pytest.mark.asyncio
async def test_project_resolution_does_not_block_the_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Slow configuration I/O runs outside the async request loop."""

    def _slow_load(_agent_id: str):
        time.sleep(0.1)
        return SimpleNamespace(project_dir=None)

    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        _slow_load,
    )
    workspace = SimpleNamespace(
        agent_id="default",
        workspace_dir=tmp_path / "workspace",
    )
    started = asyncio.get_running_loop().time()

    resolution = asyncio.create_task(
        get_project_dir_for_request(_request(tmp_path), workspace),
    )
    await asyncio.sleep(0.01)

    assert asyncio.get_running_loop().time() - started < 0.08
    assert await resolution == tmp_path.resolve()
