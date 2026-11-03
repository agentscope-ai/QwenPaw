# -*- coding: utf-8 -*-
"""Tests for Console Session project-directory request handling."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.app.routers.console import _persist_pending_project_dirs


@pytest.mark.asyncio
async def test_apply_session_project_dir_persists_before_dispatch(
    tmp_path: Path,
) -> None:
    """The first request stores its Session project snapshot."""
    updated_chat = SimpleNamespace(meta={})
    workspace = SimpleNamespace(
        chat_manager=SimpleNamespace(
            set_session_project_dirs=AsyncMock(return_value=updated_chat),
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

    result = await _persist_pending_project_dirs(workspace, chat, payload)

    assert result is updated_chat
    workspace.chat_manager.set_session_project_dirs.assert_awaited_once_with(
        "chat-1",
        [{"path": str(tmp_path.resolve()), "label": None}],
    )
    assert payload["meta"]["request_context"] == {
        "approval_level": "confirm",
    }


@pytest.mark.asyncio
async def test_apply_session_project_dir_rejects_missing_directory(
    tmp_path: Path,
) -> None:
    """An unavailable Session project never reaches the runtime.

    The pending pick is client-supplied, so a path that is not a
    directory is dropped (with a warning) rather than written onto the
    chat, where it would silently steer every later turn.
    """
    workspace = SimpleNamespace(
        chat_manager=SimpleNamespace(set_session_project_dirs=AsyncMock()),
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

    result = await _persist_pending_project_dirs(workspace, chat, payload)

    assert result is chat
    workspace.chat_manager.set_session_project_dirs.assert_not_awaited()


@pytest.mark.asyncio
async def test_apply_session_project_dir_ignores_other_context() -> None:
    """Requests without a Session project snapshot leave chat state alone."""
    workspace = SimpleNamespace(
        chat_manager=SimpleNamespace(set_session_project_dirs=AsyncMock()),
    )
    chat = SimpleNamespace(id="chat-1", meta={})
    payload = {
        "meta": {
            "request_context": {
                "approval_level": "confirm",
            },
        },
    }

    result = await _persist_pending_project_dirs(workspace, chat, payload)

    assert result is chat
    workspace.chat_manager.set_session_project_dirs.assert_not_awaited()
