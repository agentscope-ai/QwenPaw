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


@dataclass(frozen=True, slots=True)
class TerminalTaskRunReconciliationReport:
    scanned_projects: tuple[str, ...]
    scanned_terminal_tasks: int
    repaired_run_ids: tuple[str, ...]

    @property
    def repaired_count(self) -> int:
        return len(self.repaired_run_ids)


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


__all__ = [
    "TerminalTaskRunReconciliationReport",
    "reconcile_terminal_task_runs",
]
