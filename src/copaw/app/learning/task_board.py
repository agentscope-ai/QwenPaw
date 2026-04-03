# -*- coding: utf-8 -*-
"""Task-board manager: read/write a shared task list.

Supports two on-disk formats:

* **markdown** — human-editable ``TASKS.md``
* **json** — machine-friendly ``tasks.json``

Both formats are parsed into immutable ``TaskItem`` objects.
All mutations go through helper methods that perform atomic writes.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

logger = logging.getLogger(__name__)

_TASK_FILE_MD = "TASKS.md"
_TASK_FILE_JSON = "tasks.json"

# Markdown task patterns
_MD_PENDING = re.compile(
    r"^-\s*\[\s*\]\s*(?P<body>.+)$",
    re.MULTILINE,
)
_MD_IN_PROGRESS = re.compile(
    r"^-\s*\[~\]\s*(?P<body>.+)$",
    re.MULTILINE,
)
_MD_DONE = re.compile(
    r"^-\s*\[x\]\s*(?P<body>.+)$",
    re.MULTILINE | re.IGNORECASE,
)
_MD_FAILED = re.compile(
    r"^-\s*\[!\]\s*(?P<body>.+)$",
    re.MULTILINE,
)
_TAG_PATTERN = re.compile(r"#(\w[\w-]*)")
_AGENT_PATTERN = re.compile(r"@(\w[\w-]*)")
_STARTED_PATTERN = re.compile(r"\(started:\s*([^)]+)\)")
_DONE_PATTERN = re.compile(r"\(done:\s*([^)]+)\)")


@dataclass(frozen=True)
class TaskItem:
    """Immutable representation of a single task."""

    id: str
    description: str
    status: Literal["pending", "in_progress", "done", "failed"]
    tags: tuple[str, ...]
    agent: Optional[str]
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result_summary: Optional[str] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _md_id(
    description: str,
    tags: tuple[str, ...] = (),
) -> str:
    """Stable ID from the task description and tags."""
    key = f"{description}|{sorted(tags)}"
    return hashlib.sha256(key.encode()).hexdigest()[:12]


_TaskStatus = Literal["pending", "in_progress", "done", "failed"]


def _parse_md_task(
    body: str,
    status: _TaskStatus,
) -> TaskItem:
    """Parse a single markdown task line body."""
    tags = tuple(_TAG_PATTERN.findall(body))
    agent_match = _AGENT_PATTERN.search(body)
    agent = agent_match.group(1) if agent_match else None

    started_match = _STARTED_PATTERN.search(body)
    done_match = _DONE_PATTERN.search(body)

    # Clean description: remove tags, agent, timestamps
    desc = body
    for pattern in (
        _TAG_PATTERN,
        _AGENT_PATTERN,
        _STARTED_PATTERN,
        _DONE_PATTERN,
    ):
        desc = pattern.sub("", desc)
    desc = desc.strip()

    return TaskItem(
        id=_md_id(desc, tags),
        description=desc,
        status=status,
        tags=tags,
        agent=agent,
        created_at=_now_iso(),
        started_at=(
            started_match.group(1).strip() if started_match else None
        ),
        completed_at=(
            done_match.group(1).strip() if done_match else None
        ),
    )


class TaskBoardManager:
    """Read/write a task board in markdown or JSON format."""

    def __init__(
        self,
        workspace_dir: Path,
        fmt: Literal["markdown", "json"] = "markdown",
    ) -> None:
        self._workspace_dir = Path(workspace_dir)
        self._fmt = fmt

    @property
    def _path(self) -> Path:
        name = _TASK_FILE_MD if self._fmt == "markdown" else _TASK_FILE_JSON
        return self._workspace_dir / name

    # -- reading --

    def list_all(self) -> list[TaskItem]:
        if self._fmt == "markdown":
            return self._parse_md()
        return self._parse_json()

    def list_pending(self) -> list[TaskItem]:
        return [t for t in self.list_all() if t.status == "pending"]

    def list_in_progress(self) -> list[TaskItem]:
        return [t for t in self.list_all() if t.status == "in_progress"]

    def list_stuck(self, timeout_minutes: int) -> list[TaskItem]:
        now = datetime.now(timezone.utc)
        result: list[TaskItem] = []
        for task in self.list_in_progress():
            if not task.started_at:
                continue
            try:
                started = datetime.fromisoformat(task.started_at)
                elapsed = (now - started).total_seconds() / 60
                if elapsed > timeout_minutes:
                    result.append(task)
            except (ValueError, TypeError):
                continue
        return result

    # -- mutations --

    def add_task(
        self,
        description: str,
        tags: tuple[str, ...] = (),
        agent: Optional[str] = None,
    ) -> TaskItem:
        """Add a new pending task."""
        task = TaskItem(
            id=_md_id(description, tags),
            description=description,
            status="pending",
            tags=tags,
            agent=agent,
            created_at=_now_iso(),
        )
        tasks = self.list_all()
        tasks.append(task)
        self._write(tasks)
        return task

    def mark_in_progress(self, task_id: str) -> Optional[TaskItem]:
        return self._update_status(
            task_id,
            "in_progress",
            started_at=_now_iso(),
        )

    def mark_done(
        self,
        task_id: str,
        result_summary: str = "",
    ) -> Optional[TaskItem]:
        return self._update_status(
            task_id,
            "done",
            completed_at=_now_iso(),
            result_summary=result_summary,
        )

    def mark_failed(
        self,
        task_id: str,
        reason: str = "",
    ) -> Optional[TaskItem]:
        return self._update_status(
            task_id,
            "failed",
            completed_at=_now_iso(),
            result_summary=reason,
        )

    # -- private helpers --

    def _update_status(
        self,
        task_id: str,
        new_status: _TaskStatus,
        **kwargs,
    ) -> Optional[TaskItem]:
        tasks = self.list_all()
        updated = None
        new_tasks = []
        for task in tasks:
            if task.id == task_id:
                updated = replace(task, status=new_status, **kwargs)
                new_tasks.append(updated)
            else:
                new_tasks.append(task)
        if updated:
            self._write(new_tasks)
        return updated

    def _write(self, tasks: list[TaskItem]) -> None:
        if self._fmt == "markdown":
            self._write_md(tasks)
        else:
            self._write_json(tasks)

    # -- markdown I/O --

    def _parse_md(self) -> list[TaskItem]:
        if not self._path.is_file():
            return []
        text = self._path.read_text("utf-8")
        tasks: list[TaskItem] = []
        for m in _MD_PENDING.finditer(text):
            tasks.append(_parse_md_task(m.group("body"), "pending"))
        for m in _MD_IN_PROGRESS.finditer(text):
            tasks.append(
                _parse_md_task(m.group("body"), "in_progress"),
            )
        for m in _MD_DONE.finditer(text):
            tasks.append(_parse_md_task(m.group("body"), "done"))
        for m in _MD_FAILED.finditer(text):
            tasks.append(_parse_md_task(m.group("body"), "failed"))
        return tasks

    def _write_md(self, tasks: list[TaskItem]) -> None:
        sections = {"pending": [], "in_progress": [], "done": [], "failed": []}
        for t in tasks:
            sections.setdefault(t.status, []).append(t)

        lines = ["# Task Board\n"]

        if sections["pending"]:
            lines.append("\n## Pending\n")
            for t in sections["pending"]:
                lines.append(self._task_to_md_line(t))

        if sections["in_progress"]:
            lines.append("\n## In Progress\n")
            for t in sections["in_progress"]:
                lines.append(self._task_to_md_line(t))

        if sections["done"]:
            lines.append("\n## Done\n")
            for t in sections["done"]:
                lines.append(self._task_to_md_line(t))

        if sections["failed"]:
            lines.append("\n## Failed\n")
            for t in sections["failed"]:
                lines.append(self._task_to_md_line(t))

        self._atomic_write("\n".join(lines) + "\n")

    @staticmethod
    def _task_to_md_line(task: TaskItem) -> str:
        marker = {
            "pending": "[ ]",
            "in_progress": "[~]",
            "done": "[x]",
            "failed": "[!]",
        }.get(task.status, "[ ]")
        parts = [f"- {marker} {task.description}"]
        for tag in task.tags:
            parts.append(f"#{tag}")
        if task.agent:
            parts.append(f"@{task.agent}")
        if task.started_at:
            parts.append(f"(started: {task.started_at})")
        if task.completed_at:
            parts.append(f"(done: {task.completed_at})")
        return " ".join(parts)

    # -- JSON I/O --

    def _parse_json(self) -> list[TaskItem]:
        if not self._path.is_file():
            return []
        try:
            data = json.loads(self._path.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        result: list[TaskItem] = []
        for item in data.get("tasks", []):
            result.append(
                TaskItem(
                    id=item.get("id", ""),
                    description=item.get("description", ""),
                    status=item.get("status", "pending"),
                    tags=tuple(item.get("tags", [])),
                    agent=item.get("agent"),
                    created_at=item.get("created_at", ""),
                    started_at=item.get("started_at"),
                    completed_at=item.get("completed_at"),
                    result_summary=item.get("result_summary"),
                ),
            )
        return result

    def _write_json(self, tasks: list[TaskItem]) -> None:
        data = {
            "tasks": [
                {
                    "id": t.id,
                    "description": t.description,
                    "status": t.status,
                    "tags": list(t.tags),
                    "agent": t.agent,
                    "created_at": t.created_at,
                    "started_at": t.started_at,
                    "completed_at": t.completed_at,
                    "result_summary": t.result_summary,
                }
                for t in tasks
            ],
        }
        self._atomic_write(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        )

    # -- atomic file write --

    def _atomic_write(self, content: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(self._path.parent),
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp, str(self._path))
        except OSError as exc:
            logger.warning("task_board: write failed: %s", exc)
            try:
                os.unlink(tmp)
            except OSError:
                pass
