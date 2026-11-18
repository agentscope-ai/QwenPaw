# -*- coding: utf-8 -*-
# pylint: disable=too-many-return-statements
"""Startup reconciliation between terminal Task heads and their Runs.

Task and SpecialistRun heads are separate crash-safe aggregates.  A process
can therefore stop after terminalizing a Task but before applying the matching
Run transition.  This module repairs only that derived Run state; it never
replays provider work or changes a Task result.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

from domain.enums import (
    TERMINAL_SPECIALIST_STATUSES,
    SpecialistRunStatus,
    TaskStatus,
)

from .execution_models import TaskRecord
from .execution_store import ExecutionStateConflict, ProjectExecutionStore


_TASK_TO_RUN_STATUS = {
    TaskStatus.SUCCEEDED: SpecialistRunStatus.SUCCEEDED,
    TaskStatus.FAILED: SpecialistRunStatus.FAILED,
    TaskStatus.CANCELLED: SpecialistRunStatus.CANCELLED,
    TaskStatus.QUARANTINED: SpecialistRunStatus.STALE,
}
_FINAL_MARKERS = {
    SpecialistRunStatus.SUCCEEDED: "SUCCESS",
    SpecialistRunStatus.FAILED: "FAILED",
    SpecialistRunStatus.CANCELLED: "CANCELLED",
    SpecialistRunStatus.STALE: "STALE",
}
_SUCCESS_BRIDGE_STATUSES = frozenset(
    {
        SpecialistRunStatus.QUEUED,
        SpecialistRunStatus.QUEUED_CAPACITY,
        SpecialistRunStatus.WAITING_AUTHORIZATION,
    },
)

# Admission states whose Run can never be dispatched again once the process
# that admitted it is gone.  WAITING_AUTHORIZATION is deliberately absent: a
# person may still approve that Run in a later session.
_ORPHANED_QUEUED_STATUSES = frozenset(
    {
        SpecialistRunStatus.QUEUED,
        SpecialistRunStatus.QUEUED_CAPACITY,
        SpecialistRunStatus.WAITING_RUNTIME,
    },
)
ORPHANED_QUEUED_RUN_GRACE = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class TerminalTaskRunReconciliationReport:
    scanned_projects: tuple[str, ...]
    scanned_terminal_tasks: int
    repaired_run_ids: tuple[str, ...]

    @property
    def repaired_count(self) -> int:
        return len(self.repaired_run_ids)


@dataclass(frozen=True, slots=True)
class OrphanedQueuedRunReport:
    scanned_projects: tuple[str, ...]
    cancelled_run_ids: tuple[str, ...]

    @property
    def cancelled_count(self) -> int:
        return len(self.cancelled_run_ids)


def _text_from_mapping(value: Mapping[str, Any] | None) -> str | None:
    if not value:
        return None
    for key in (
        "message",
        "summary",
        "finalSummary",
        "final_summary",
        "quarantineReason",
        "reason",
    ):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    artifact = value.get("artifactVersion")
    if isinstance(artifact, Mapping):
        name = artifact.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def _summary(task: TaskRecord) -> str:
    detail = _text_from_mapping(task.error) or _text_from_mapping(task.result)
    if detail:
        return detail[:2000]
    return (
        f"Reconciled terminal {task.kind.value} Task {task.task_id}: "
        f"{task.status.value}"
    )


def _transition_run_from_task(
    executions: ProjectExecutionStore,
    task: TaskRecord,
) -> bool:
    if task.run_id is None:
        return False
    target = _TASK_TO_RUN_STATUS.get(task.status)
    if target is None:
        return False
    run = executions.get_run(task.project_id, task.run_id)
    if run.status in TERMINAL_SPECIALIST_STATUSES:
        return False

    # SUCCEEDED is intentionally not a legal direct transition from admission
    # or authorization-wait states.  Bridge through RUNNING_MODEL so startup
    # repair obeys the same state machine as live execution.
    if (
        target is SpecialistRunStatus.SUCCEEDED
        and run.status in _SUCCESS_BRIDGE_STATUSES
    ):
        try:
            run = executions.transition_run(
                task.project_id,
                run.run_id,
                expected_status=run.status,
                status=SpecialistRunStatus.RUNNING_MODEL,
            )
        except ExecutionStateConflict:
            run = executions.get_run(task.project_id, run.run_id)
            if run.status in TERMINAL_SPECIALIST_STATUSES:
                return False

    updates = {
        "final_marker": _FINAL_MARKERS[target],
        "final_summary_text": _summary(task),
    }
    for _attempt in range(2):
        if run.status in TERMINAL_SPECIALIST_STATUSES:
            return False
        try:
            executions.transition_run(
                task.project_id,
                run.run_id,
                expected_status=run.status,
                status=target,
                updates=updates,
            )
            return True
        except ExecutionStateConflict:
            run = executions.get_run(task.project_id, run.run_id)
    return False


def reconcile_terminal_task_runs(
    data_root: str | Path,
    project_ids: Sequence[str],
) -> TerminalTaskRunReconciliationReport:
    """Repair active Runs whose associated Task is already terminal.

    The input project order is normalized for deterministic startup behavior.
    Within a Project, ``list_tasks`` is newest-first; when multiple terminal
    Tasks reference one active Run, the newest durable Task determines it and
    subsequent Tasks observe the now-terminal Run.
    """

    executions = ProjectExecutionStore(Path(data_root))
    normalized_projects = tuple(sorted(dict.fromkeys(project_ids)))
    repaired: list[str] = []
    scanned_terminal = 0
    for project_id in normalized_projects:
        for task in executions.list_tasks(project_id):
            if task.status not in _TASK_TO_RUN_STATUS:
                continue
            scanned_terminal += 1
            if _transition_run_from_task(executions, task):
                assert task.run_id is not None
                repaired.append(task.run_id)
    return TerminalTaskRunReconciliationReport(
        scanned_projects=normalized_projects,
        scanned_terminal_tasks=scanned_terminal,
        repaired_run_ids=tuple(repaired),
    )


def reconcile_orphaned_queued_runs(
    data_root: str | Path,
    project_ids: Sequence[str],
    *,
    now: datetime | None = None,
    grace: timedelta = ORPHANED_QUEUED_RUN_GRACE,
) -> OrphanedQueuedRunReport:
    """Fail enqueued Runs no executor can ever pick up again.

    A Run head is admitted before its Task.  A process that dies in that
    window leaves a QUEUED Run with no Task behind, and only R2V video Runs
    carry the stable identity needed to rebuild the missing Task at the next
    boot (see the admission-gap recovery, which runs first and either rebuilds
    or fails those).  Every other orphan would sit in the progress projection
    as "waiting" forever: nothing alive can dispatch it, and nothing alive
    will ever terminalize it.  CANCELLED, not FAILED: no attempt was made, so
    nothing failed -- recovery simply stops pretending it will run.

    Runs younger than ``grace`` are left alone so a restart loop cannot reap
    an admission whose Task write is merely slow.
    """

    moment = now or datetime.now(UTC)
    executions = ProjectExecutionStore(Path(data_root))
    normalized_projects = tuple(sorted(dict.fromkeys(project_ids)))
    cancelled: list[str] = []
    for project_id in normalized_projects:
        claimed = {
            task.run_id
            for task in executions.list_tasks(project_id)
            if task.run_id
        }
        for run in executions.list_specialist_runs(project_id):
            if run.status not in _ORPHANED_QUEUED_STATUSES:
                continue
            if run.run_id in claimed:
                continue
            if moment - run.updated_at < grace:
                continue
            try:
                executions.transition_run(
                    project_id,
                    run.run_id,
                    expected_status=run.status,
                    status=SpecialistRunStatus.CANCELLED,
                    updates={
                        "final_marker": "CANCELLED",
                        "final_summary_text": (
                            "ORPHANED_QUEUED_RUN: the process that admitted "
                            "this Run ended before its Task existed; no "
                            "executor can dispatch it"
                        ),
                    },
                )
            except ExecutionStateConflict:
                continue
            cancelled.append(run.run_id)
    return OrphanedQueuedRunReport(
        scanned_projects=normalized_projects,
        cancelled_run_ids=tuple(cancelled),
    )


__all__ = [
    "OrphanedQueuedRunReport",
    "TerminalTaskRunReconciliationReport",
    "reconcile_orphaned_queued_runs",
    "reconcile_terminal_task_runs",
]
