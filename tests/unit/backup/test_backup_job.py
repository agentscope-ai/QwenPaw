# -*- coding: utf-8 -*-
"""Unit tests for backup cron job builder."""
from __future__ import annotations

from qwenpaw.app.crons.backup_job import (
    BACKUP_JOB_ID,
    BACKUP_JOB_NAME,
    build_backup_cron_job,
)


def test_build_backup_cron_job_defaults() -> None:
    job = build_backup_cron_job()
    assert job.id == BACKUP_JOB_ID
    assert job.name == BACKUP_JOB_NAME
    assert job.enabled is True
    assert job.schedule.cron == "0 2 * * *"
    assert job.task_type == "agent"
    assert job.request is not None
    assert job.runtime.max_concurrency == 1


def test_build_backup_cron_job_custom_schedule() -> None:
    job = build_backup_cron_job(
        schedule="30 3 * * *",
        timezone="Asia/Shanghai",
    )
    assert job.schedule.cron == "30 3 * * *"
    assert job.schedule.timezone == "Asia/Shanghai"


def test_build_backup_cron_job_dispatch_target() -> None:
    job = build_backup_cron_job(user_id="u1", session_id="s1")
    assert job.dispatch.target.user_id == "u1"
    assert job.dispatch.target.session_id == "s1"
