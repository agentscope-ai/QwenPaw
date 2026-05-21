# -*- coding: utf-8 -*-
"""Tests for the todo_write tool and its helpers."""

# pylint: disable=redefined-outer-name
import json
from pathlib import Path

import pytest

from qwenpaw.agents.tools.todo import (
    _load_todos,
    _merge_todos,
    _save_todos,
    _todos_path,
    todo_write,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """Return a temporary workspace directory."""
    return tmp_path


@pytest.fixture
def session_id() -> str:
    """Return a stable test session ID."""
    return "test-session-abc"


# ---------------------------------------------------------------------------
# _todos_path
# ---------------------------------------------------------------------------


def test_todos_path(tmp_workspace: Path, session_id: str) -> None:
    """Path should be workspace/sessions/<session_id>/todos.json."""
    path = _todos_path(tmp_workspace, session_id)
    assert path == tmp_workspace / "sessions" / session_id / "todos.json"


# ---------------------------------------------------------------------------
# _load_todos / _save_todos
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_todos_missing_file(tmp_workspace: Path) -> None:
    """Loading from a non-existent file returns an empty list."""
    path = tmp_workspace / "sessions" / "x" / "todos.json"
    result = await _load_todos(path)
    assert result == []


@pytest.mark.asyncio
async def test_save_and_load_round_trip(tmp_workspace: Path) -> None:
    """Saved todos can be loaded back without modification."""
    path = tmp_workspace / "sessions" / "s1" / "todos.json"
    todos = [
        {"id": "t1", "content": "Do X", "status": "pending"},
        {"id": "t2", "content": "Do Y", "status": "in_progress"},
    ]
    await _save_todos(path, todos)
    loaded = await _load_todos(path)
    assert loaded == todos


@pytest.mark.asyncio
async def test_save_creates_parent_dirs(tmp_workspace: Path) -> None:
    """Save creates intermediate directories automatically."""
    path = tmp_workspace / "deep" / "nested" / "todos.json"
    await _save_todos(path, [{"id": "a", "content": "B", "status": "pending"}])
    assert path.exists()


# ---------------------------------------------------------------------------
# _merge_todos
# ---------------------------------------------------------------------------


def test_merge_todos_replaces_existing() -> None:
    """An item with the same id is replaced in-place."""
    existing = [
        {"id": "t1", "content": "Old", "status": "pending"},
        {"id": "t2", "content": "Keep", "status": "pending"},
    ]
    updates = [{"id": "t1", "content": "New", "status": "in_progress"}]
    merged = _merge_todos(existing, updates)
    assert len(merged) == 2
    assert merged[0] == {"id": "t1", "content": "New", "status": "in_progress"}
    assert merged[1] == {"id": "t2", "content": "Keep", "status": "pending"}


def test_merge_todos_appends_new() -> None:
    """An item with a new id is appended to the list."""
    existing = [{"id": "t1", "content": "A", "status": "pending"}]
    updates = [{"id": "t2", "content": "B", "status": "pending"}]
    merged = _merge_todos(existing, updates)
    assert len(merged) == 2
    assert merged[1]["id"] == "t2"


def test_merge_todos_empty_existing() -> None:
    """Merging into an empty list returns the updates."""
    updates = [{"id": "t1", "content": "X", "status": "done"}]
    merged = _merge_todos([], updates)
    assert merged == updates


def test_merge_todos_preserves_order() -> None:
    """Existing order is preserved; new items append at the end."""
    existing = [
        {"id": "a", "content": "A", "status": "pending"},
        {"id": "b", "content": "B", "status": "pending"},
        {"id": "c", "content": "C", "status": "pending"},
    ]
    updates = [
        {"id": "c", "content": "C-updated", "status": "in_progress"},
        {"id": "d", "content": "D-new", "status": "pending"},
    ]
    merged = _merge_todos(existing, updates)
    ids = [item["id"] for item in merged]
    assert ids == ["a", "b", "c", "d"]
    assert merged[2]["content"] == "C-updated"


# ---------------------------------------------------------------------------
# todo_write (integration)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_todo_write_no_context() -> None:
    """Without context, the tool returns an error message."""
    from qwenpaw.config.context import (
        set_current_workspace_dir,
        set_current_session_id,
    )

    set_current_workspace_dir(None)
    set_current_session_id(None)

    resp = await todo_write(
        [{"id": "t1", "content": "Do thing", "status": "pending"}],
    )
    text = resp.content[0]["text"]
    assert "context not available" in text


@pytest.mark.asyncio
async def test_todo_write_creates_file(
    tmp_workspace: Path,
    session_id: str,
) -> None:
    """todo_write persists todos to the session file."""
    from qwenpaw.config.context import (
        set_current_workspace_dir,
        set_current_session_id,
    )

    set_current_workspace_dir(tmp_workspace)
    set_current_session_id(session_id)

    todos = [{"id": "t1", "content": "Write tests", "status": "pending"}]
    resp = await todo_write(todos, merge=False)

    saved_path = _todos_path(tmp_workspace, session_id)
    assert saved_path.exists()

    data = json.loads(saved_path.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["id"] == "t1"

    result = json.loads(resp.content[0]["text"])
    assert result == data


@pytest.mark.asyncio
async def test_todo_write_merge_default(
    tmp_workspace: Path,
    session_id: str,
) -> None:
    """Second todo_write call merges by default."""
    from qwenpaw.config.context import (
        set_current_workspace_dir,
        set_current_session_id,
    )

    set_current_workspace_dir(tmp_workspace)
    set_current_session_id(session_id)

    await todo_write(
        [{"id": "t1", "content": "Step 1", "status": "pending"}],
        merge=False,
    )
    await todo_write(
        [
            {"id": "t1", "content": "Step 1", "status": "in_progress"},
            {"id": "t2", "content": "Step 2", "status": "pending"},
        ],
        merge=True,
    )

    saved_path = _todos_path(tmp_workspace, session_id)
    data = json.loads(saved_path.read_text(encoding="utf-8"))
    assert len(data) == 2
    assert data[0]["status"] == "in_progress"
    assert data[1]["id"] == "t2"


@pytest.mark.asyncio
async def test_todo_write_skips_invalid_items(
    tmp_workspace: Path,
    session_id: str,
) -> None:
    """Items missing id or content are silently skipped."""
    from qwenpaw.config.context import (
        set_current_workspace_dir,
        set_current_session_id,
    )

    set_current_workspace_dir(tmp_workspace)
    set_current_session_id(session_id)

    resp = await todo_write(
        [
            {"id": "", "content": "No id", "status": "pending"},
            {"id": "t1", "content": "", "status": "pending"},
            {"id": "t2", "content": "Valid item", "status": "pending"},
        ],
        merge=False,
    )
    result = json.loads(resp.content[0]["text"])
    assert len(result) == 1
    assert result[0]["id"] == "t2"


@pytest.mark.asyncio
async def test_todo_write_normalises_invalid_status(
    tmp_workspace: Path,
    session_id: str,
) -> None:
    """Unknown status values are normalised to 'pending'."""
    from qwenpaw.config.context import (
        set_current_workspace_dir,
        set_current_session_id,
    )

    set_current_workspace_dir(tmp_workspace)
    set_current_session_id(session_id)

    await todo_write(
        [{"id": "t1", "content": "X", "status": "unknown_status"}],
        merge=False,
    )
    saved_path = _todos_path(tmp_workspace, session_id)
    data = json.loads(saved_path.read_text(encoding="utf-8"))
    assert data[0]["status"] == "pending"
