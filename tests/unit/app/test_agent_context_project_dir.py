# -*- coding: utf-8 -*-
"""Tests for Files API project-directory request context."""

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
