# -*- coding: utf-8 -*-
"""Unit tests for JsonJobRepository tolerant loading (issue #4835)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from qwenpaw.app.crons.repo.json_repo import JsonJobRepository

_VALID_JOB = {
    "name": "valid-job",
    "task_type": "text",
    "text": "hello",
    "schedule": {"type": "cron", "cron": "0 9 * * *"},
    "dispatch": {"target": {"user_id": "u1", "session_id": "s1"}},
}
_INVALID_JOB = {"name": "broken"}  # missing required schedule + dispatch


def _write_jobs(path: Path, jobs: list) -> None:
    path.write_text(
        json.dumps({"version": 1, "jobs": jobs}),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_load_keeps_valid_drops_invalid(tmp_path: Path) -> None:
    jobs_path = tmp_path / "jobs.json"
    _write_jobs(jobs_path, [_VALID_JOB, _INVALID_JOB])

    result = await JsonJobRepository(jobs_path).load()

    assert [job.name for job in result.jobs] == ["valid-job"]
    assert result.version == 1


@pytest.mark.asyncio
async def test_load_all_valid_is_unchanged(tmp_path: Path) -> None:
    jobs_path = tmp_path / "jobs.json"
    _write_jobs(jobs_path, [_VALID_JOB])

    result = await JsonJobRepository(jobs_path).load()

    assert len(result.jobs) == 1


@pytest.mark.asyncio
async def test_load_only_invalid_returns_empty(tmp_path: Path) -> None:
    jobs_path = tmp_path / "jobs.json"
    _write_jobs(jobs_path, [_INVALID_JOB])

    result = await JsonJobRepository(jobs_path).load()

    assert result.jobs == []
