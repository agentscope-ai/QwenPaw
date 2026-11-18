# -*- coding: utf-8 -*-
"""Reclaim eligible scratch and transaction history only for this request."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.media_files.task_scratch import (
    confirm_project_reclaim,
    history_reclaim_kept,
    read_reclaim_confirmation,
    release_orphaned_scratch,
)

from services.runtime_files.path_safety import is_link_path
from .store import ProjectNotFound, UnsafeProjectPath
from .transaction_gc import collect_project_transactions


@dataclass(frozen=True, slots=True)
class HistoryReclaimResult:
    """What one on-demand sweep actually freed."""

    project_id: str
    history_kept: bool
    confirmed_at: datetime | None
    removed_transactions: int
    transaction_bytes: int
    released_files: int
    released_bytes: int


def reclaim_project_history(
    services: Any,
    project_id: str,
    *,
    now: datetime | None = None,
) -> HistoryReclaimResult:
    """Sweep one Project's settled history now; report the real delta.

    The Project is addressed on disk before anything is deleted, so a malformed
    or unknown id fails without touching a byte.  Existence is the only
    assertion: a Project whose ``project.json`` no longer validates is
    precisely the case where freeing its settled history still has to work.
    """

    moment = now or datetime.now(timezone.utc)
    project_root = Path(services.projects.project_root(project_id))
    with services.projects.lifecycle_lock(project_id):
        return _reclaim_locked(services, project_id, project_root, moment)


def _reclaim_locked(
    services: Any,
    project_id: str,
    project_root: Path,
    moment: datetime,
) -> HistoryReclaimResult:
    if any(
        is_link_path(path)
        for path in (
            project_root,
            services.projects.project_path(project_id),
            project_root / "runtime",
            project_root / "runtime" / "transactions",
        )
    ):
        raise UnsafeProjectPath(
            "Cannot reclaim through a redirected project path"
        )
    if not services.projects.project_path(project_id).is_file():
        raise ProjectNotFound(f"Project does not exist: {project_id}")
    if history_reclaim_kept(project_root):
        return HistoryReclaimResult(
            project_id=project_id,
            history_kept=True,
            confirmed_at=read_reclaim_confirmation(project_root),
            removed_transactions=0,
            transaction_bytes=0,
            released_files=0,
            released_bytes=0,
        )
    confirmed_at = confirm_project_reclaim(project_root, now=moment)
    count, size = collect_project_transactions(project_root, confirmed=True)
    scratch = release_orphaned_scratch(
        services,
        now=moment,
        project_ids=(project_id,),
        reclaim_legacy=True,
    )
    return HistoryReclaimResult(
        project_id=project_id,
        history_kept=False,
        confirmed_at=confirmed_at,
        removed_transactions=count,
        transaction_bytes=size,
        released_files=scratch.removed_files,
        released_bytes=scratch.removed_bytes,
    )
