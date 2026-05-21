# -*- coding: utf-8 -*-
"""TodoWrite tool for Coding Mode.

Allows the agent to maintain a structured TODO list during complex
coding tasks. The list is persisted per-session and read by the
CodingModeMixin to emit real-time SSE updates to the frontend.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Literal

import aiofiles
import aiofiles.os
from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from ...config.context import (
    get_current_session_id,
    get_current_workspace_dir,
)

logger = logging.getLogger(__name__)

TodoStatus = Literal["pending", "in_progress", "done", "cancelled"]

_TODOS_FILENAME = "todos.json"


def _todos_path(workspace_dir: Path, session_id: str) -> Path:
    """Return the path to the todos JSON file for a session.

    Args:
        workspace_dir: Agent workspace directory.
        session_id: Current session identifier.

    Returns:
        Path to the todos.json file.
    """
    return workspace_dir / "sessions" / session_id / _TODOS_FILENAME


async def _load_todos(path: Path) -> list[dict[str, Any]]:
    """Load todos from disk. Returns empty list if file absent.

    Args:
        path: Path to todos.json file.

    Returns:
        List of todo item dicts.
    """
    if not path.exists():
        return []
    try:
        async with aiofiles.open(path, "r", encoding="utf-8") as f:
            raw = await f.read()
        return json.loads(raw)
    except Exception:
        logger.warning("Failed to load todos from %s", path, exc_info=True)
        return []


async def _save_todos(
    path: Path,
    todos: list[dict[str, Any]],
) -> None:
    """Persist todos to disk, creating parent dirs as needed.

    Args:
        path: Path to todos.json file.
        todos: List of todo item dicts to persist.
    """
    await aiofiles.os.makedirs(path.parent, exist_ok=True)
    async with aiofiles.open(path, "w", encoding="utf-8") as f:
        await f.write(json.dumps(todos, ensure_ascii=False, indent=2))


def _merge_todos(
    existing: list[dict[str, Any]],
    updates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge update items into existing list by id.

    Items in *updates* whose ``id`` already exists in *existing* replace
    the existing entry.  New ids are appended in order.

    Args:
        existing: Current todos from disk.
        updates: Incoming todo items from the agent.

    Returns:
        Merged list preserving original order for existing ids.
    """
    index = {item["id"]: i for i, item in enumerate(existing)}
    result = list(existing)
    for item in updates:
        item_id = item.get("id")
        if item_id and item_id in index:
            result[index[item_id]] = item
        else:
            result.append(item)
            if item_id:
                index[item_id] = len(result) - 1
    return result


async def todo_write(
    todos: list[dict],
    merge: bool = True,
) -> ToolResponse:
    """Maintain a structured TODO list for the current coding task.

    Call this tool at the START of a multi-step task to lay out all
    planned steps, then update individual item statuses as work
    progresses. Only ONE item should be ``in_progress`` at a time.

    Args:
        todos: List of todo items. Each item must have:
            - ``id`` (str): Stable identifier chosen by you,
              e.g. ``"task-1"``. Keep it short and consistent.
            - ``content`` (str): Human-readable description of
              the task.
            - ``status`` (str): One of ``"pending"``,
              ``"in_progress"``, ``"done"``, ``"cancelled"``.
        merge: When ``True`` (default), items are merged with the
            existing list by ``id`` — only provided fields are
            updated. When ``False``, the entire list is replaced.

    Returns:
        ``ToolResponse`` containing the current todo list as JSON.
    """
    workspace_dir = get_current_workspace_dir()
    session_id = get_current_session_id()

    if workspace_dir is None or not session_id:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text="todo_write: context not available (no session).",
                ),
            ],
        )

    # Validate each item has required keys
    cleaned: list[dict[str, Any]] = []
    for item in todos:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id", "")).strip()
        content = str(item.get("content", "")).strip()
        status = str(item.get("status", "pending")).strip()
        if status not in ("pending", "in_progress", "done", "cancelled"):
            status = "pending"
        if not item_id or not content:
            continue
        cleaned.append({"id": item_id, "content": content, "status": status})

    path = _todos_path(Path(workspace_dir), session_id)

    if merge:
        existing = await _load_todos(path)
        final = _merge_todos(existing, cleaned)
    else:
        final = cleaned

    await _save_todos(path, final)

    result_json = json.dumps(final, ensure_ascii=False)
    return ToolResponse(
        content=[TextBlock(type="text", text=result_json)],
    )
