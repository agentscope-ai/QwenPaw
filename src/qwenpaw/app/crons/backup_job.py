# -*- coding: utf-8 -*-
"""Helper to build a CronJobSpec for the daily backup task."""
from __future__ import annotations

from .models import (
    CronJobRequest,
    CronJobSpec,
    DispatchSpec,
    DispatchTarget,
    JobRuntimeSpec,
    ScheduleSpec,
)

BACKUP_JOB_ID = "_backup"
BACKUP_JOB_NAME = "Daily Asset Backup"


def build_backup_cron_job(
    *,
    schedule: str = "0 2 * * *",
    user_id: str = "system",
    session_id: str = "backup",
    channel: str = "internal",
    timezone: str = "UTC",
    timeout_seconds: int = 300,
) -> CronJobSpec:
    """Create a :class:`CronJobSpec` for the daily asset backup task.

    Parameters
    ----------
    schedule:
        Cron expression (5-field). Defaults to ``"0 2 * * *"`` (02:00 daily).
    user_id / session_id:
        Dispatch target identifiers.
    channel:
        Dispatch channel name.
    timezone:
        Timezone for the cron schedule.
    timeout_seconds:
        Maximum execution time for a single backup run.
    """
    return CronJobSpec(
        id=BACKUP_JOB_ID,
        name=BACKUP_JOB_NAME,
        enabled=True,
        schedule=ScheduleSpec(cron=schedule, timezone=timezone),
        task_type="agent",
        request=CronJobRequest(
            input="Run daily asset backup",
            user_id=user_id,
            session_id=session_id,
        ),
        dispatch=DispatchSpec(
            channel=channel,
            target=DispatchTarget(
                user_id=user_id,
                session_id=session_id,
            ),
        ),
        runtime=JobRuntimeSpec(
            max_concurrency=1,
            timeout_seconds=timeout_seconds,
        ),
        meta={"source": "backup_scheduler"},
    )
