# -*- coding: utf-8 -*-
"""Retry local publication of an already materialized provider result."""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import Any, TypeVar

from domain.enums import TaskStatus
from services.runtime_files.execution_store import (
    ExecutionStateConflict,
    ProjectExecutionStore,
)
from services.runtime_files.errors import LockTimeoutError
from services.runtime_files.execution_models import TaskRecord
from utils.logger import setup_logger

logger = setup_logger(__name__)
_Result = TypeVar("_Result")
MAX_PUBLICATION_ATTEMPTS = 5


async def commit_with_lock_retry(
    commit_if_live: Callable[[], _Result],
    *,
    project_id: str,
    task_id: str,
) -> _Result:
    """Retry lock contention without repeating provider work.

    The callback must recheck durable cancellation, input freshness, and
    whether its stable transaction already committed on every attempt.
    No lock is retained during the cancellable backoff. Other failures
    retain their existing failure/quarantine behavior.
    """
    for attempt in range(MAX_PUBLICATION_ATTEMPTS):
        try:
            return await asyncio.to_thread(commit_if_live)
        except LockTimeoutError:
            if attempt + 1 == MAX_PUBLICATION_ATTEMPTS:
                raise
            logger.warning(
                "media publication lock busy; retrying local commit "
                "project=%s task=%s attempt=%s/%s",
                project_id,
                task_id,
                attempt + 1,
                MAX_PUBLICATION_ATTEMPTS,
            )
            await asyncio.sleep(min(0.25 * 2**attempt, 2.0))
    raise AssertionError("Publication retry budget exhausted")


async def record_materialized_result(
    executions: ProjectExecutionStore,
    *,
    project_id: str,
    task_id: str,
    result: Mapping[str, Any],
    progress: float,
) -> TaskRecord:
    """Persist paid output before indexing, tolerating concurrent publication.

    This Runtime write also takes the Project lifecycle lock. Retrying only
    the later Project commit leaves successfully generated media vulnerable
    to another image's long commit. Every retry rechecks terminal state so
    cancellation still wins without resurrecting or resubmitting the Task.
    """

    def record_if_live() -> TaskRecord:
        latest = executions.get_task(project_id, task_id)
        if (
            latest.status is not TaskStatus.RUNNING
            or latest.result is not None
        ):
            return latest
        try:
            return executions.transition_task(
                project_id,
                task_id,
                expected_status=TaskStatus.RUNNING,
                status=TaskStatus.RUNNING,
                updates={
                    "progress": progress,
                    "result": dict(result),
                    "output_refs": [str(result["outputRef"])],
                },
            )
        except ExecutionStateConflict:
            return executions.get_task(project_id, task_id)

    return await commit_with_lock_retry(
        record_if_live,
        project_id=project_id,
        task_id=task_id,
    )
