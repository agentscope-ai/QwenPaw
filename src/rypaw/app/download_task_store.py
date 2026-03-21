# -*- coding: utf-8 -*-
"""In-memory store for tracking background model download tasks.

Multiple downloads can run concurrently. Completed/failed results are retained
until explicitly cleared so the frontend can poll for the final state.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class DownloadTaskStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DownloadTask(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    repo_id: str
    filename: Optional[str] = None
    backend: str
    source: str
    status: DownloadTaskStatus = DownloadTaskStatus.PENDING
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


_tasks: Dict[str, DownloadTask] = {}
_lock = asyncio.Lock()


async def create_task(
    repo_id: str,
    filename: Optional[str],
    backend: str,
    source: str,
) -> DownloadTask:
    """Create a new pending download task."""
    async with _lock:
        task = DownloadTask(
            repo_id=repo_id,
            filename=filename,
            backend=backend,
            source=source,
        )
        _tasks[task.task_id] = task
        return task


async def get_tasks(backend: Optional[str] = None) -> List[DownloadTask]:
    """Return all tasks, optionally filtered by backend."""
    async with _lock:
        tasks = list(_tasks.values())
    if backend:
        tasks = [t for t in tasks if t.backend == backend]
    return tasks


async def get_task(task_id: str) -> Optional[DownloadTask]:
    """Return a specific task by ID."""
    async with _lock:
        return _tasks.get(task_id)


async def update_status(
    task_id: str,
    status: DownloadTaskStatus,
    *,
    error: Optional[str] = None,
    result: Optional[Dict[str, Any]] = None,
) -> None:
    """Update the status of a task. No-op if task_id doesn't exist."""
    async with _lock:
        task = _tasks.get(task_id)
        if task is None:
            return
        task.status = status
        task.updated_at = time.time()
        if error is not None:
            task.error = error
        if result is not None:
            task.result = result


async def cancel_task(task_id: str) -> bool:
    """Cancel a pending or downloading task.

    Returns True if cancelled, False if task not found or not cancellable.
    """
    async with _lock:
        task = _tasks.get(task_id)
        if task is None:
            return False
        if task.status not in (
            DownloadTaskStatus.PENDING,
            DownloadTaskStatus.DOWNLOADING,
        ):
            return False
        task.status = DownloadTaskStatus.CANCELLED
        task.updated_at = time.time()
        return True


async def clear_completed(backend: Optional[str] = None) -> None:
    """Remove tasks in a terminal state (completed/failed/cancelled)."""
    async with _lock:
        to_remove = [
            tid
            for tid, t in _tasks.items()
            if t.status
            in (
                DownloadTaskStatus.COMPLETED,
                DownloadTaskStatus.FAILED,
                DownloadTaskStatus.CANCELLED,
            )
            and (backend is None or t.backend == backend)
        ]
        for tid in to_remove:
            del _tasks[tid]
