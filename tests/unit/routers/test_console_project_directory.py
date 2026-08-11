# -*- coding: utf-8 -*-
"""Tests for Console Session project-directory request handling.

The console router persists *pending* picks (sent with a new chat's
first message) onto the chat; resolution itself happens once per turn
inside ContextVarsSetupHook.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.app.routers.console import _persist_pending_project_dirs


@pytest.mark.asyncio
async def test_pending_singular_persists_before_dispatch(
    tmp_path: Path,
) -> None:
    """A legacy single-value pick is stored as a one-entry list."""
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
        None,
    )
    assert payload["meta"]["request_context"] == {
        "approval_level": "confirm",
    }


@pytest.mark.asyncio
async def test_pending_plural_wins_over_singular(tmp_path: Path) -> None:
    primary = tmp_path / "main"
    extra = tmp_path / "extra"
    primary.mkdir()
    extra.mkdir()
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
                "session_project_dirs": [
                    {"path": str(primary), "label": "main"},
                    str(extra),
                ],
                "session_project_dir": "/legacy/ignored",
                "session_project_name": "My Project",
            },
        },
    }

    result = await _persist_pending_project_dirs(workspace, chat, payload)

    assert result is updated_chat
    workspace.chat_manager.set_session_project_dirs.assert_awaited_once_with(
        "chat-1",
        [
            {"path": str(primary.resolve()), "label": "main"},
            {"path": str(extra.resolve()), "label": None},
        ],
        "My Project",
    )


@pytest.mark.asyncio
async def test_pending_missing_directory_is_dropped(tmp_path: Path) -> None:
    """A non-directory entry is skipped, not failed: the user's message
    must still go through."""
    workspace = SimpleNamespace(
        chat_manager=SimpleNamespace(
            set_session_project_dirs=AsyncMock(),
        ),
    )
    chat = SimpleNamespace(id="chat-1", meta={})
    missing = tmp_path / "missing"
    payload = {
        "meta": {
            "request_context": {
                "session_project_dirs": [str(missing)],
            },
        },
    }

    result = await _persist_pending_project_dirs(workspace, chat, payload)

    assert result is chat
    workspace.chat_manager.set_session_project_dirs.assert_not_awaited()


@pytest.mark.asyncio
async def test_pending_never_overwrites_existing_override(
    tmp_path: Path,
) -> None:
    workspace = SimpleNamespace(
        chat_manager=SimpleNamespace(
            set_session_project_dirs=AsyncMock(),
        ),
    )
    chat = SimpleNamespace(
        id="chat-1",
        meta={
            "runtime_context": {
                "project_dirs": [{"path": "/already", "label": None}],
            },
        },
    )
    payload = {
        "meta": {
            "request_context": {
                "session_project_dirs": [str(tmp_path)],
            },
        },
    }

    result = await _persist_pending_project_dirs(workspace, chat, payload)

    assert result is chat
    workspace.chat_manager.set_session_project_dirs.assert_not_awaited()


@pytest.mark.asyncio
async def test_pending_ignores_other_context() -> None:
    """Requests without a pending snapshot leave chat state alone."""
    workspace = SimpleNamespace(
        chat_manager=SimpleNamespace(
            set_session_project_dirs=AsyncMock(),
        ),
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
