# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

import pytest

from domain.enums import (
    SpecialistRole,
    SpecialistRunStatus,
    TaskKind,
    TaskStatus,
)
from services.runtime_files.execution_models import (
    SpecialistRunRecord,
    TaskAttemptStatus,
    TaskRecord,
)
from services.runtime_files.execution_store import ProjectExecutionStore
from services.runtime_files.models import ReviewPolicy
from services.runtime_files.reconciliation import reconcile_terminal_task_runs


pytestmark = pytest.mark.unit

PROJECT_ID = "project-1"


def _store(tmp_path: Path) -> ProjectExecutionStore:
    root = tmp_path / PROJECT_ID
    root.mkdir()
    (root / "project.json").write_text("{}\n", encoding="utf-8")
    return ProjectExecutionStore(tmp_path)


def _set_run_status(
    store: ProjectExecutionStore,
    run_id: str,
    target: SpecialistRunStatus,
) -> None:
    if target is SpecialistRunStatus.QUEUED:
        return
    current = store.transition_run(
        PROJECT_ID,
        run_id,
        expected_status=SpecialistRunStatus.QUEUED,
        status=SpecialistRunStatus.RUNNING_MODEL,
    )
    if target is not SpecialistRunStatus.RUNNING_MODEL:
        store.transition_run(
            PROJECT_ID,
            run_id,
            expected_status=current.status,
            status=target,
        )


def _terminal_pair(
    store: ProjectExecutionStore,
    *,
    suffix: str,
    kind: TaskKind,
    task_status: TaskAttemptStatus,
    run_status: SpecialistRunStatus,
    detail: str,
) -> tuple[str, str]:
    run_id = f"run-{suffix}"
    task_id = f"task-{suffix}"
    round_id = f"round-{suffix}"
    request_id = f"request-{suffix}"
    store.create_run(
        SpecialistRunRecord(
            run_id=run_id,
            project_id=PROJECT_ID,
            round_id=round_id,
            role=SpecialistRole.R2V_GENERATION_DIRECTOR,
            target_refs=[f"element:{suffix}"],
            input_generation=1,
            input_etag="sha256:input",
            caused_by_request_id=request_id,
            review_policy=ReviewPolicy.AUTO_FIX,
        ),
    )
    _set_run_status(store, run_id, run_status)
    store.create_task(
        TaskRecord(
            task_id=task_id,
            project_id=PROJECT_ID,
            round_id=round_id,
            run_id=run_id,
            kind=kind,
            request_fingerprint=f"sha256:{suffix}",
            input_generation=1,
            input_etag="sha256:input",
            caused_by_request_id=request_id,
            review_policy=ReviewPolicy.AUTO_FIX,
        ),
    )
    store.append_attempt(
        PROJECT_ID,
        task_id,
        event_id=f"event-{suffix}-running",
        attempt_id=f"attempt-{suffix}",
        status=TaskAttemptStatus.RUNNING,
    )
    kwargs = (
        {"output": {"summary": detail}}
        if task_status is TaskAttemptStatus.SUCCEEDED
        else {"error": {"message": detail}}
    )
    store.append_attempt(
        PROJECT_ID,
        task_id,
        event_id=f"event-{suffix}-terminal",
        attempt_id=f"attempt-{suffix}",
        status=task_status,
        **kwargs,
    )
    return run_id, task_id


def test_terminal_tasks_reconcile_active_runs_for_all_file_runtime_kinds(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    cases = (
        (
            "image",
            TaskKind.IMAGE_GENERATION,
            TaskAttemptStatus.SUCCEEDED,
            SpecialistRunStatus.QUEUED,
            SpecialistRunStatus.SUCCEEDED,
            "image generated",
            "SUCCESS",
        ),
        (
            "local",
            TaskKind.AI_EDIT_EXECUTE,
            TaskAttemptStatus.FAILED,
            SpecialistRunStatus.WAITING_AUTHORIZATION,
            SpecialistRunStatus.FAILED,
            "ffmpeg failed",
            "FAILED",
        ),
        (
            "source",
            TaskKind.SOURCE_INTELLIGENCE,
            TaskAttemptStatus.CANCELLED,
            SpecialistRunStatus.RUNNING_MODEL,
            SpecialistRunStatus.CANCELLED,
            "source cancelled",
            "CANCELLED",
        ),
        (
            "r2v",
            TaskKind.R2V_GENERATION,
            TaskAttemptStatus.QUARANTINED,
            SpecialistRunStatus.WAITING_RUNTIME,
            SpecialistRunStatus.STALE,
            "project input stale",
            "STALE",
        ),
    )
    run_ids: list[str] = []
    for suffix, kind, task_status, run_status, *_rest in cases:
        run_id, _task_id = _terminal_pair(
            store,
            suffix=suffix,
            kind=kind,
            task_status=task_status,
            run_status=run_status,
            detail=cases[len(run_ids)][5],
        )
        run_ids.append(run_id)

    report = reconcile_terminal_task_runs(tmp_path, [PROJECT_ID])
    assert report.scanned_projects == (PROJECT_ID,)
    assert report.scanned_terminal_tasks == 4
    assert report.repaired_count == 4
    assert set(report.repaired_run_ids) == set(run_ids)
    for case, run_id in zip(cases, run_ids, strict=True):
        expected_status, detail, marker = case[4], case[5], case[6]
        run = store.get_run(PROJECT_ID, run_id)
        assert run.status is expected_status
        assert run.final_marker == marker
        assert run.final_summary_text == detail


def test_terminal_task_run_reconciliation_is_idempotent(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    run_id, _task_id = _terminal_pair(
        store,
        suffix="r2v",
        kind=TaskKind.R2V_GENERATION,
        task_status=TaskAttemptStatus.QUARANTINED,
        run_status=SpecialistRunStatus.WAITING_RUNTIME,
        detail="stale provider result",
    )
    first = reconcile_terminal_task_runs(tmp_path, [PROJECT_ID, PROJECT_ID])
    reconciled = store.get_run(PROJECT_ID, run_id)
    second = reconcile_terminal_task_runs(tmp_path, [PROJECT_ID])

    assert first.repaired_run_ids == (run_id,)
    assert second.scanned_terminal_tasks == 1
    assert second.repaired_count == 0
    assert store.get_run(PROJECT_ID, run_id) == reconciled
    assert (
        store.get_task(PROJECT_ID, "task-r2v").status is TaskStatus.QUARANTINED
    )
