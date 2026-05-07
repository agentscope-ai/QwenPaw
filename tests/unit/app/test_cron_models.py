# -*- coding: utf-8 -*-
from __future__ import annotations

import json

import pytest

from qwenpaw.app.crons.models import JobsFile
from qwenpaw.app.crons.repo.json_repo import JsonJobRepository


LEGACY_AGENT_JOB = {
    "id": "job-legacy",
    "name": "Legacy agent job",
    "enabled": True,
    "schedule": {"type": "cron", "cron": "0 9 * * *", "timezone": "UTC"},
    "task_type": "agent",
    "request": {},
    "dispatch": {
        "type": "channel",
        "channel": "console",
        "target": {
            "user_id": "target-user",
            "session_id": "target-session",
        },
        "mode": "final",
        "meta": {},
    },
    "execution": {"session": {"mode": "dispatch"}},
    "runtime": {
        "max_concurrency": 1,
        "timeout_seconds": 30,
        "misfire_grace_seconds": 60,
    },
    "meta": {},
}


def test_jobs_file_accepts_legacy_agent_request_without_input() -> None:
    jobs_file = JobsFile.model_validate(
        {
            "version": 1,
            "jobs": [LEGACY_AGENT_JOB],
        }
    )

    job = jobs_file.jobs[0]
    assert job.request is not None
    assert job.request.input is None
    assert job.request.user_id == "target-user"


@pytest.mark.asyncio
async def test_json_repo_load_accepts_legacy_agent_request_without_input(
    tmp_path,
) -> None:
    repo = JsonJobRepository(tmp_path / "jobs.json")
    repo.path.write_text(
        json.dumps({"version": 1, "jobs": [LEGACY_AGENT_JOB]}),
        encoding="utf-8",
    )

    jobs_file = await repo.load()

    job = jobs_file.jobs[0]
    assert job.request is not None
    assert job.request.input is None
    assert job.request.user_id == "target-user"


def test_jobs_file_preserves_explicit_request_input() -> None:
    explicit_job = {
        **LEGACY_AGENT_JOB,
        "id": "job-modern",
        "request": {
            "input": [
                {
                    "role": "user",
                    "type": "message",
                    "content": [{"type": "text", "text": "hello"}],
                }
            ],
            "session_id": "request-session",
            "user_id": "request-user",
        },
    }

    jobs_file = JobsFile.model_validate(
        {
            "version": 1,
            "jobs": [explicit_job],
        }
    )

    job = jobs_file.jobs[0]
    assert job.request is not None
    assert job.request.input == explicit_job["request"]["input"]
    assert job.request.user_id == "target-user"
