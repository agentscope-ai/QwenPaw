# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
from __future__ import annotations

import json
from pathlib import Path

import pytest

from qwenpaw.app.crons.repo.json_repo import (
    JsonJobRepository,
    migrate_legacy_weixin_jobs_file,
)
from qwenpaw.app.crons.models import JobsFile
from tests.unit.app.conftest import make_cron_job_spec, make_execution_record


@pytest.fixture
def repo(tmp_path: Path) -> JsonJobRepository:
    return JsonJobRepository(tmp_path / "jobs.json")


# ---------------------------------------------------------------------------
# load / save round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_returns_empty_when_file_missing(repo: JsonJobRepository):
    result = await repo.load()
    assert result.jobs == []


@pytest.mark.asyncio
async def test_save_and_load_round_trip(repo: JsonJobRepository):
    spec = make_cron_job_spec(job_id="j1")
    jf = JobsFile(version=1, jobs=[spec])
    await repo.save(jf)

    loaded = await repo.load()
    assert len(loaded.jobs) == 1
    assert loaded.jobs[0].id == "j1"


# ---------------------------------------------------------------------------
# append_history / get_history / delete_history
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_append_history_prepends_and_limits(repo: JsonJobRepository):
    records = []
    for _ in range(3):
        rec = make_execution_record(status="success")
        records = await repo.append_history("j1", rec, limit=2)

    # Only the two most recent survive the limit=2 cap.
    assert len(records) == 2


@pytest.mark.asyncio
async def test_get_history_returns_empty_before_any_appends(
    repo: JsonJobRepository,
):
    assert await repo.get_history("missing-job") == []


@pytest.mark.asyncio
async def test_delete_history_removes_file(repo: JsonJobRepository):
    rec = make_execution_record()
    await repo.append_history("j1", rec)
    assert await repo.get_history("j1") != []

    await repo.delete_history("j1")
    assert await repo.get_history("j1") == []


# ---------------------------------------------------------------------------
# prune_orphan_history
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prune_orphan_history_removes_unknown_jobs(
    repo: JsonJobRepository,
):
    await repo.append_history("alive", make_execution_record())
    await repo.append_history("orphan", make_execution_record())

    await repo.prune_orphan_history(valid_job_ids={"alive"})

    assert await repo.get_history("alive") != []
    assert await repo.get_history("orphan") == []


# ---------------------------------------------------------------------------
# migrate_legacy_weixin_jobs_file
# ---------------------------------------------------------------------------


def test_migrate_weixin_session_ids(tmp_path: Path):
    jobs_path = tmp_path / "jobs.json"
    data = {
        "version": 1,
        "jobs": [
            {
                "id": "j1",
                "name": "Legacy Job",
                "dispatch": {
                    "target": {"session_id": "weixin:u1", "user_id": "u1"},
                },
            },
        ],
    }
    jobs_path.write_text(json.dumps(data), encoding="utf-8")

    migrate_legacy_weixin_jobs_file(jobs_path)

    result = json.loads(jobs_path.read_text(encoding="utf-8"))
    assert result["jobs"][0]["dispatch"]["target"]["session_id"] == "wechat:u1"


def test_migrate_is_idempotent(tmp_path: Path):
    jobs_path = tmp_path / "jobs.json"
    data = {
        "version": 1,
        "jobs": [
            {
                "id": "j1",
                "dispatch": {
                    "target": {"session_id": "wechat:u1", "user_id": "u1"},
                },
            },
        ],
    }
    original = json.dumps(data)
    jobs_path.write_text(original, encoding="utf-8")

    migrate_legacy_weixin_jobs_file(jobs_path)

    # File unchanged — no backup created, content identical.
    assert jobs_path.read_text(encoding="utf-8") == original


def test_migrate_noop_when_file_missing(tmp_path: Path):
    # Should not raise.
    migrate_legacy_weixin_jobs_file(tmp_path / "nonexistent.json")
