# -*- coding: utf-8 -*-
from __future__ import annotations

from copaw.app.crons.manager import CronManager
from copaw.app.crons.models import CronJobSpec, JobsFile
from copaw.app.crons.repo.base import BaseJobRepository


class _MemoryRepo(BaseJobRepository):
    def __init__(self, jobs_file: JobsFile):
        self._jobs_file = jobs_file

    async def load(self) -> JobsFile:
        return self._jobs_file

    async def save(self, jobs_file: JobsFile) -> None:
        self._jobs_file = jobs_file


async def test_start_skips_invalid_persisted_cron_job() -> None:
    invalid_job = CronJobSpec.model_validate(
        {
            "id": "bad-job",
            "name": "Bad Job",
            "enabled": True,
            "schedule": {"type": "cron", "cron": "0 */30 * * *", "timezone": "UTC"},
            "task_type": "text",
            "text": "hello",
            "dispatch": {
                "type": "channel",
                "channel": "console",
                "target": {"user_id": "u1", "session_id": "s1"},
            },
        }
    )
    valid_job = CronJobSpec.model_validate(
        {
            "id": "good-job",
            "name": "Good Job",
            "enabled": True,
            "schedule": {"type": "cron", "cron": "0 * * * *", "timezone": "UTC"},
            "task_type": "text",
            "text": "hello",
            "dispatch": {
                "type": "channel",
                "channel": "console",
                "target": {"user_id": "u1", "session_id": "s1"},
            },
        }
    )
    repo = _MemoryRepo(JobsFile(version=1, jobs=[invalid_job, valid_job]))
    manager = CronManager(repo=repo, runner=object(), channel_manager=object())

    await manager.start()

    bad_state = manager.get_state("bad-job")
    good_state = manager.get_state("good-job")
    assert bad_state.last_status == "error"
    assert bad_state.last_error is not None
    assert good_state.next_run_at is not None

    await manager.stop()
