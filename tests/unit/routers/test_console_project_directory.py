# -*- coding: utf-8 -*-
"""Tests for Console Session project-directory request handling."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from qwenpaw.app.routers.console import _apply_session_project_dir


@pytest.mark.asyncio
async def test_apply_session_project_dir_persists_before_dispatch(
    tmp_path: Path,
) -> None:
    """The first request stores its Session project snapshot."""
    updated_chat = SimpleNamespace(meta={})
    workspace = SimpleNamespace(
        chat_manager=SimpleNamespace(
            set_project_dir=AsyncMock(return_value=updated_chat),
        ),
    )
    chat = SimpleNamespace(id="chat-1", meta={})
    payload = {
        "meta": {
            "request_context": {
                "approval_level": "confirm",
                "session_project_dir": str(tmp_path),
            },
        },
    }

    result = await _apply_session_project_dir(workspace, chat, payload)

    assert result is updated_chat
    workspace.chat_manager.set_project_dir.assert_awaited_once_with(
        "chat-1",
        str(tmp_path.resolve()),
    )
    assert payload["meta"]["request_context"] == {
        "approval_level": "confirm",
    }


@pytest.mark.asyncio
async def test_apply_session_project_dir_rejects_missing_directory(
    tmp_path: Path,
) -> None:
    """An unavailable Session project never reaches the runtime."""
    workspace = SimpleNamespace(
        chat_manager=SimpleNamespace(set_project_dir=AsyncMock()),
    )
    chat = SimpleNamespace(id="chat-1", meta={})
    missing = tmp_path / "missing"
    payload = {
        "meta": {
            "request_context": {
                "session_project_dir": str(missing),
            },
        },
    }

    with pytest.raises(
        HTTPException,
        match="Project directory is unavailable",
    ):
        await _apply_session_project_dir(workspace, chat, payload)

    workspace.chat_manager.set_project_dir.assert_not_awaited()


@pytest.mark.asyncio
async def test_apply_session_project_dir_ignores_other_context() -> None:
    """Requests without a Session project snapshot leave chat state alone."""
    workspace = SimpleNamespace(
        chat_manager=SimpleNamespace(set_project_dir=AsyncMock()),
    )
    chat = SimpleNamespace(id="chat-1", meta={})
    payload = {
        "meta": {
            "request_context": {
                "approval_level": "confirm",
            },
        },
    }

    result = await _apply_session_project_dir(workspace, chat, payload)

    assert result is chat
    workspace.chat_manager.set_project_dir.assert_not_awaited()
