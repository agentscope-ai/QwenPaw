# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""Unit tests for CronManager.

Covers: lifecycle, CRUD, state cleanup, concurrent write serialization,
and manager-level tolerance for failed job registration during start.

Note: the tests here exercise CronManager behavior only. They do NOT
verify fixes for #4835 (load-layer corruption), #4957 (TaskEngineMixin
stale status — in agentscope-runtime), or #4232 (SafeJSONSession
concurrent writes — already fixed upstream).
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from qwenpaw.app.crons.manager import CronManager
from qwenpaw.app.crons.models import CronJobState, ScheduleSpec
from tests.unit.app.conftest import (
    InMemoryJobRepository,
    make_cron_job_spec,
    make_execution_record,
)


@pytest.fixture
def repo() -> InMemoryJobRepository:
    return InMemoryJobRepository()


@pytest.fixture
def manager(repo: InMemoryJobRepository) -> CronManager:
    return CronManager(
        repo=repo,
        workspace=MagicMock(),
        channel_manager=AsyncMock(),
    )


# ---------------------------------------------------------------------------
# start / stop lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_is_idempotent(manager: CronManager):
    await manager.start()
    await manager.start()  # second call must not raise or double-start
    assert manager._started is True
    await manager.stop()


@pytest.mark.asyncio
async def test_start_loads_existing_jobs(repo: InMemoryJobRepository):
    spec = make_cron_job_spec(job_id="preloaded")
    await repo.upsert_job(spec)

    mgr = CronManager(
        repo=repo,
        workspace=MagicMock(),
        channel_manager=AsyncMock(),
    )
    await mgr.start()

    jobs = await mgr.list_jobs()
    assert any(j.id == "preloaded" for j in jobs)
    await mgr.stop()


# ---------------------------------------------------------------------------
# start() tolerance — single bad job must not crash the entire start()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_tolerates_individual_job_with_invalid_schedule(
    repo: InMemoryJobRepository,
):
    # Inject a valid job so the manager has something to register, then
    # simulate a second job whose _register_or_update would raise.
    spec = make_cron_job_spec(job_id="good")
    await repo.upsert_job(spec)

    mgr = CronManager(
        repo=repo,
        workspace=MagicMock(),
        channel_manager=AsyncMock(),
    )

    # Patch _register_or_update to raise on the first call (simulates a bad
    # stored cron expression that slips past Pydantic after a schema change).
    original = mgr._register_or_update
    call_count = 0

    async def _patched(s):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ValueError("simulated corrupt schedule")
        return await original(s)

    mgr._register_or_update = _patched
    # start() must not propagate the error from a single bad job
    await mgr.start()
    assert mgr._started is True
    await mgr.stop()


# ---------------------------------------------------------------------------
# create_or_replace_job / list_jobs / get_job
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_or_replace_job_persists_to_repo(
    manager: CronManager,
    repo: InMemoryJobRepository,
):
    await manager.start()
    spec = make_cron_job_spec(job_id="j1")

    await manager.create_or_replace_job(spec)

    jobs = await repo.list_jobs()
    assert any(j.id == "j1" for j in jobs)
    await manager.stop()


@pytest.mark.asyncio
async def test_create_or_replace_job_registers_with_scheduler(
    manager: CronManager,
):
    await manager.start()
    spec = make_cron_job_spec(job_id="j1")

    await manager.create_or_replace_job(spec)

    assert manager._scheduler.get_job("j1") is not None
    await manager.stop()


# ---------------------------------------------------------------------------
# delete_job
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_job_removes_from_scheduler_and_repo(
    manager: CronManager,
    repo: InMemoryJobRepository,
):
    await manager.start()
    spec = make_cron_job_spec(job_id="j-del")
    await manager.create_or_replace_job(spec)

    deleted = await manager.delete_job("j-del")

    assert deleted is True
    assert manager._scheduler.get_job("j-del") is None
    assert await repo.get_job("j-del") is None
    await manager.stop()


@pytest.mark.asyncio
async def test_delete_job_returns_false_for_missing(manager: CronManager):
    await manager.start()
    result = await manager.delete_job("ghost")
    assert result is False
    await manager.stop()


# ---------------------------------------------------------------------------
# get_history / get_state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_history_delegates_to_repo(
    manager: CronManager,
    repo: InMemoryJobRepository,
):
    rec = make_execution_record(status="success")
    await repo.append_history("j1", rec)

    history = await manager.get_history("j1")

    assert len(history) == 1
    assert history[0].status == "success"


@pytest.mark.asyncio
async def test_get_state_returns_default_for_unknown_job(manager: CronManager):
    state = manager.get_state("ghost")
    assert isinstance(state, CronJobState)
    assert state.last_status is None


@pytest.mark.asyncio
async def test_execute_once_records_last_run_in_job_timezone(
    manager: CronManager,
    repo: InMemoryJobRepository,
):
    spec = make_cron_job_spec(job_id="tz-job")
    spec = spec.model_copy(
        update={
            "schedule": ScheduleSpec(
                type="cron",
                cron="0 3 * * *",
                timezone="Asia/Shanghai",
            ),
        },
    )
    await repo.upsert_job(spec)
    manager._executor.execute = AsyncMock(return_value={})

    await manager._execute_once(spec, trigger="manual")

    state = manager.get_state("tz-job")
    history = await manager.get_history("tz-job")
    assert state.last_run_at is not None
    assert state.last_run_at.utcoffset() == timedelta(hours=8)
    assert history[0].run_at == state.last_run_at


# ---------------------------------------------------------------------------
# delete_job cleans up in-memory state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_job_clears_in_memory_state(manager: CronManager):
    await manager.start()
    spec = make_cron_job_spec(job_id="stale")
    await manager.create_or_replace_job(spec)

    # Inject synthetic state so the job looks "running"
    manager._states["stale"] = CronJobState(last_status="running")

    await manager.delete_job("stale")

    # After delete, get_state must return a fresh default, not the stale one
    state = manager.get_state("stale")
    assert state.last_status is None
    await manager.stop()


# ---------------------------------------------------------------------------
# concurrent create_or_replace_job serialized by _lock
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_create_or_replace_jobs_all_land(
    manager: CronManager,
    repo: InMemoryJobRepository,
):
    await manager.start()
    specs = [
        make_cron_job_spec(job_id=f"j{i}", name=f"Job {i}") for i in range(5)
    ]

    await asyncio.gather(*(manager.create_or_replace_job(s) for s in specs))

    all_ids = {j.id for j in await repo.list_jobs()}
    assert all_ids == {s.id for s in specs}
    await manager.stop()


# ---------------------------------------------------------------------------
# run_job — raises for unknown job, fires task for known job
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_job_raises_for_unknown_job(manager: CronManager):
    await manager.start()
    with pytest.raises(KeyError, match="ghost"):
        await manager.run_job("ghost")
    await manager.stop()


@pytest.mark.asyncio
async def test_run_job_creates_background_task_for_known_job(
    manager: CronManager,
    repo: InMemoryJobRepository,
):
    spec = make_cron_job_spec(job_id="runme")
    await repo.upsert_job(spec)
    await manager.start()

    with patch.object(
        manager,
        "_execute_once",
        new_callable=AsyncMock,
    ) as mock_exec:
        await manager.run_job("runme")
        # Give the event loop a tick to schedule the task.
        await asyncio.sleep(0)

    mock_exec.assert_called_once()
    await manager.stop()
