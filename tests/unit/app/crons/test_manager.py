# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from copaw.app.crons.manager import CronManager
from copaw.app.crons.models import (
    CronJobRequest,
    CronJobSpec,
    DispatchSpec,
    DispatchTarget,
    JobsFile,
    ScheduleSpec,
)
from copaw.app.crons.repo.base import BaseJobRepository


class _InMemoryRepo(BaseJobRepository):
    def __init__(self, jobs_file: JobsFile):
        self._jobs_file = jobs_file

    async def load(self) -> JobsFile:
        return self._jobs_file

    async def save(self, jobs_file: JobsFile) -> None:
        self._jobs_file = jobs_file


@pytest.mark.asyncio
async def test_start_skips_invalid_cron_and_keeps_valid_job() -> None:
    valid_job = CronJobSpec(
        id="job-valid",
        name="valid",
        schedule=ScheduleSpec(cron="*/5 * * * *", timezone="UTC"),
        task_type="agent",
        request=CronJobRequest(input="ping"),
        dispatch=DispatchSpec(
            channel="console",
            target=DispatchTarget(user_id="u1", session_id="s1"),
        ),
    )
    # 5 fields but invalid for APScheduler hour field (step > 23).
    invalid_job = CronJobSpec(
        id="job-invalid",
        name="invalid",
        schedule=ScheduleSpec(cron="0 */30 * * *", timezone="UTC"),
        task_type="agent",
        request=CronJobRequest(input="ping"),
        dispatch=DispatchSpec(
            channel="console",
            target=DispatchTarget(user_id="u2", session_id="s2"),
        ),
    )

    repo = _InMemoryRepo(JobsFile(jobs=[valid_job, invalid_job]))
    manager = CronManager(repo=repo, runner=None, channel_manager=None)

    await manager.start()
    try:
        state_valid = manager.get_state("job-valid")
        state_invalid = manager.get_state("job-invalid")

        assert state_valid.next_run_at is not None
        assert state_valid.last_status is None

        assert state_invalid.next_run_at is None
        assert state_invalid.last_status == "error"
        assert state_invalid.last_error is not None
        assert "invalid schedule" in state_invalid.last_error
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_create_or_replace_raises_on_invalid_cron() -> None:
    """create_or_replace_job must reject an invalid cron before persisting."""
    repo = _InMemoryRepo(JobsFile(jobs=[]))
    manager = CronManager(repo=repo, runner=None, channel_manager=None)
    await manager.start()
    try:
        invalid = CronJobSpec(
            id="job-bad",
            name="bad-cron",
            schedule=ScheduleSpec(cron="0 */30 * * *", timezone="UTC"),
            task_type="agent",
            request=CronJobRequest(input="ping"),
            dispatch=DispatchSpec(
                channel="console",
                target=DispatchTarget(user_id="u1", session_id="s1"),
            ),
        )
        with pytest.raises(ValueError):
            await manager.create_or_replace_job(invalid)

        # Nothing should have been persisted
        saved = await repo.list_jobs()
        assert len(saved) == 0
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_create_or_replace_raises_without_started() -> None:
    """Validation runs even when the manager has not been started."""
    repo = _InMemoryRepo(JobsFile(jobs=[]))
    manager = CronManager(repo=repo, runner=None, channel_manager=None)
    # Do NOT call start()
    invalid = CronJobSpec(
        id="job-bad2",
        name="bad-cron-2",
        schedule=ScheduleSpec(cron="0 */30 * * *", timezone="UTC"),
        task_type="agent",
        request=CronJobRequest(input="ping"),
        dispatch=DispatchSpec(
            channel="console",
            target=DispatchTarget(user_id="u1", session_id="s1"),
        ),
    )
    with pytest.raises(ValueError):
        await manager.create_or_replace_job(invalid)

    saved = await repo.list_jobs()
    assert len(saved) == 0
