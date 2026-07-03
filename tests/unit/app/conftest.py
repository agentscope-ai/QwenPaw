# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
from __future__ import annotations

from datetime import datetime, timezone as _tz
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from qwenpaw.app.crons.manager import CronManager
from qwenpaw.app.crons.models import (
    CronExecutionRecord,
    CronJobRequest,
    CronJobSpec,
    DispatchSpec,
    DispatchTarget,
    JobsFile,
    ScheduleSpec,
)
from qwenpaw.app.crons.repo.base import BaseJobRepository


class InMemoryJobRepository(BaseJobRepository):
    """In-memory BaseJobRepository for unit tests."""

    def __init__(self) -> None:
        self._jobs_file = JobsFile(version=1, jobs=[])
        self._history: dict[str, list[CronExecutionRecord]] = {}

    async def load(self) -> JobsFile:
        return self._jobs_file.model_copy(deep=True)

    async def save(self, jobs_file: JobsFile) -> None:
        self._jobs_file = jobs_file.model_copy(deep=True)

    async def get_history(self, job_id: str) -> list[CronExecutionRecord]:
        return list(self._history.get(job_id, []))

    async def append_history(
        self,
        job_id: str,
        record: CronExecutionRecord,
        *,
        limit: int = 50,
    ) -> list[CronExecutionRecord]:
        records = list(self._history.get(job_id, []))
        records.insert(0, record)
        del records[limit:]
        self._history[job_id] = records
        return list(records)

    async def delete_history(self, job_id: str) -> None:
        self._history.pop(job_id, None)

    async def prune_orphan_history(self, valid_job_ids: set[str]) -> None:
        for job_id in list(self._history):
            if job_id not in valid_job_ids:
                del self._history[job_id]


@pytest.fixture
def in_memory_repo() -> InMemoryJobRepository:
    return InMemoryJobRepository()


@pytest.fixture
def mock_workspace() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_channel_manager() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def cron_manager(
    in_memory_repo: InMemoryJobRepository,
    mock_workspace: MagicMock,
    mock_channel_manager: AsyncMock,
) -> CronManager:
    return CronManager(
        repo=in_memory_repo,
        workspace=mock_workspace,
        channel_manager=mock_channel_manager,
    )


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def make_cron_schedule(
    *,
    cron: str = "0 9 * * mon",
    timezone: str = "UTC",
) -> ScheduleSpec:
    return ScheduleSpec(type="cron", cron=cron, timezone=timezone)


def make_once_schedule(
    *,
    run_at: Optional[datetime] = None,
    timezone: str = "UTC",
) -> ScheduleSpec:
    if run_at is None:
        run_at = datetime(2030, 1, 1, 9, 0, tzinfo=_tz.utc)
    return ScheduleSpec(type="once", run_at=run_at, timezone=timezone)


def make_dispatch_target(
    *,
    user_id: str = "u1",
    session_id: str = "console:u1",
) -> DispatchTarget:
    return DispatchTarget(user_id=user_id, session_id=session_id)


def make_cron_job_spec(
    *,
    job_id: Optional[str] = "job-1",
    name: str = "Test Job",
    cron: str = "0 9 * * mon",
    user_id: str = "u1",
    session_id: str = "console:u1",
    task_type: str = "agent",
    text: Optional[str] = None,
    enabled: bool = True,
) -> CronJobSpec:
    target = make_dispatch_target(user_id=user_id, session_id=session_id)
    dispatch = DispatchSpec(target=target)
    schedule = make_cron_schedule(cron=cron)

    kwargs: dict = {
        "name": name,
        "enabled": enabled,
        "schedule": schedule,
        "task_type": task_type,
        "dispatch": dispatch,
    }
    if job_id is not None:
        kwargs["id"] = job_id
    if task_type == "text":
        kwargs["text"] = text or "Hello"
    else:
        kwargs["request"] = CronJobRequest(input="ping")

    return CronJobSpec(**kwargs)


def make_execution_record(
    *,
    status: str = "success",
    run_at: Optional[datetime] = None,
    error: Optional[str] = None,
    trigger: str = "scheduled",
) -> CronExecutionRecord:
    if run_at is None:
        run_at = datetime.now(tz=_tz.utc)
    return CronExecutionRecord(
        run_at=run_at,
        status=status,
        error=error,
        trigger=trigger,
    )
