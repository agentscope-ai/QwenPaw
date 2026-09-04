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

from qwenpaw.app.crons.contracts import ServiceCronJob
from qwenpaw.app.crons.manager import CronManager
from qwenpaw.app.crons.models import (
    CronJobSpec,
    CronJobState,
    ScheduleSpec,
)
from tests.unit.app.conftest import (
    InMemoryJobRepository,
    make_cron_job_spec,
    make_execution_record,
)


@pytest.fixture(autouse=True)
def _no_real_inbox_writes(monkeypatch):
    """Prevent cron tests from writing to the real inbox store.

    CronManager._execute_once calls append_inbox_event on success,
    which writes to WORKING_DIR/inbox_events.json.  Without this
    guard any test that exercises _execute_once (directly or via
    the scheduler) would leak real data to disk.
    """
    monkeypatch.setattr(
        "qwenpaw.app.crons.manager.append_inbox_event",
        AsyncMock(),
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


def _review_gated_job(job_id: str = "imported") -> CronJobSpec:
    job = make_cron_job_spec(job_id=job_id, enabled=False)
    portability = {
        "source": "codex",
        "source_id": "automation-1",
        "requires_review": True,
        "safety": "disabled_until_explicit_promotion",
    }
    dispatch = job.dispatch.model_copy(
        update={"meta": {"portability": dict(portability)}},
    )
    return job.model_copy(
        update={
            "meta": {"portability": portability},
            "dispatch": dispatch,
        },
    )


def _legacy_provenance_job(job_id: str = "legacy-imported") -> CronJobSpec:
    job = make_cron_job_spec(job_id=job_id, enabled=True)
    return job.model_copy(
        update={
            "meta": {
                "portability": {
                    "source": "codex",
                    "source_id": "legacy-automation",
                },
            },
        },
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
async def test_keepalive_task_lifecycle(manager: CronManager):
    """A self-contained keepalive task runs while cron is started.

    The keepalive keeps the asyncio event loop ticking so APScheduler's
    AsyncIOScheduler keeps processing due jobs even when the loop is
    otherwise idle (see issue #6471).
    """
    await manager.start()
    task = manager._keepalive_task
    assert task is not None
    assert not task.done()
    await manager.stop()
    assert manager._keepalive_task is None
    assert task.done()


@pytest.mark.asyncio
async def test_service_job_uses_scheduler_jitter(
    repo: InMemoryJobRepository,
):
    callback = AsyncMock()
    declaration = ServiceCronJob(
        key="maintenance",
        cron="0 23 * * *",
        callback=callback,
        jitter_seconds=60,
    )
    workspace = MagicMock()
    workspace.memory_manager.list_cron_jobs.return_value = [declaration]
    mgr = CronManager(
        repo=repo,
        workspace=workspace,
        channel_manager=AsyncMock(),
        agent_id="test-agent",
    )

    await mgr.start()

    job = mgr._scheduler.get_job("_service:memory:maintenance")
    assert job is not None
    assert job.trigger.jitter == 60
    callback.assert_not_awaited()
    await mgr.stop()


@pytest.mark.asyncio
async def test_start_registers_jobs_declared_by_memory_manager(
    repo: InMemoryJobRepository,
):
    workspace = MagicMock()
    callback = AsyncMock()
    workspace.memory_manager.list_cron_jobs.return_value = [
        ServiceCronJob(
            key="maintenance",
            cron="0 8 * * *",
            callback=callback,
        ),
    ]
    mgr = CronManager(
        repo=repo,
        workspace=workspace,
        channel_manager=AsyncMock(),
        agent_id="test-agent",
    )

    await mgr.start()

    assert mgr._scheduler.get_job("_service:memory:maintenance") is not None
    await mgr.stop()


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
# pause_job / resume_job
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pause_job_persists_disabled_state(
    manager: CronManager,
    repo: InMemoryJobRepository,
):
    await repo.upsert_job(make_cron_job_spec(job_id="j-pause"))

    await manager.pause_job("j-pause")

    stored = await manager.get_job("j-pause")
    assert stored is not None
    assert stored.enabled is False
    listed = await manager.list_jobs()
    assert listed[0].enabled is False


@pytest.mark.asyncio
async def test_resume_job_persists_enabled_state(
    manager: CronManager,
    repo: InMemoryJobRepository,
):
    await repo.upsert_job(
        make_cron_job_spec(job_id="j-resume", enabled=False),
    )

    await manager.resume_job("j-resume")

    stored = await repo.get_job("j-resume")
    assert stored is not None
    assert stored.enabled is True


@pytest.mark.asyncio
async def test_pause_and_resume_raise_for_missing_job(manager: CronManager):
    with pytest.raises(KeyError, match="missing"):
        await manager.pause_job("missing")
    with pytest.raises(KeyError, match="missing"):
        await manager.resume_job("missing")


@pytest.mark.asyncio
async def test_review_gated_job_cannot_run_or_resume(
    manager: CronManager,
    repo: InMemoryJobRepository,
):
    job = _review_gated_job()
    await repo.upsert_job(job)
    await manager.start()
    manager._executor.execute = AsyncMock()

    with pytest.raises(PermissionError, match="explicit promotion"):
        await manager.run_job(job.id or "")
    with pytest.raises(PermissionError, match="explicit promotion"):
        await manager.resume_job(job.id or "")

    stored = await repo.get_job(job.id or "")
    assert stored is not None
    assert stored.enabled is False
    manager._executor.execute.assert_not_awaited()
    await manager.stop()


@pytest.mark.asyncio
async def test_legacy_import_provenance_is_repaired_and_fail_closed(
    manager: CronManager,
    repo: InMemoryJobRepository,
):
    job = _legacy_provenance_job()
    await repo.upsert_job(job)
    await manager.start()

    stored = await repo.get_job(job.id or "")
    assert stored is not None
    assert stored.enabled is False
    assert stored.meta["portability"]["requires_review"] is True
    assert stored.dispatch.meta["portability"]["safety"] == (
        "disabled_until_explicit_promotion"
    )
    assert stored.request is not None
    assert (
        stored.request.request_context["portability_review_required"] is True
    )

    with pytest.raises(PermissionError, match="explicit promotion"):
        await manager.run_job(job.id or "")
    with pytest.raises(PermissionError, match="explicit promotion"):
        await manager.resume_job(job.id or "")

    promoted = await manager.promote_imported_job(job.id or "")
    assert promoted.enabled is False
    assert promoted.meta["portability"]["promoted_at"]
    await manager.stop()


@pytest.mark.asyncio
async def test_generic_update_cannot_enable_or_clear_review_gate(
    manager: CronManager,
    repo: InMemoryJobRepository,
):
    job = _review_gated_job()
    await repo.upsert_job(job)

    with pytest.raises(PermissionError, match="remain disabled"):
        await manager.create_or_replace_job(
            job.model_copy(update={"enabled": True}),
        )
    with pytest.raises(PermissionError, match="only be cleared"):
        await manager.create_or_replace_job(
            job.model_copy(update={"meta": {}}),
        )

    assert await repo.get_job(job.id or "") == job


@pytest.mark.asyncio
async def test_promotion_clears_review_gate_but_keeps_job_disabled(
    manager: CronManager,
    repo: InMemoryJobRepository,
):
    job = _review_gated_job()
    await repo.upsert_job(job)
    await manager.start()

    promoted = await manager.promote_imported_job(
        job.id or "",
        actor="test-reviewer",
    )

    assert promoted.enabled is False
    portability = promoted.meta["portability"]
    assert portability["requires_review"] is False
    assert portability["safety"] == "reviewed_disabled"
    assert portability["promoted_by"] == "test-reviewer"
    await manager.resume_job(job.id or "")
    stored = await repo.get_job(job.id or "")
    assert stored is not None
    assert stored.enabled is True
    await manager.stop()


@pytest.mark.asyncio
async def test_remote_job_promotion_requires_explicit_local_project_dir(
    manager: CronManager,
    repo: InMemoryJobRepository,
):
    job = _review_gated_job("remote-no-mapping")
    portability = dict(job.meta["portability"])
    portability.update(
        {
            "source_cwd_remote_or_unverified": True,
            "source_cwd_binding": "omitted_remote_or_unverified",
        },
    )
    job = job.model_copy(update={"meta": {"portability": portability}})
    await repo.upsert_job(job)

    with pytest.raises(PermissionError, match="local project_dir"):
        await manager.promote_imported_job(job.id or "")

    stored = await repo.get_job(job.id or "")
    assert stored is not None
    assert stored.meta["portability"]["requires_review"] is True


@pytest.mark.asyncio
async def test_remote_job_can_be_promoted_after_local_directory_mapping(
    manager: CronManager,
    repo: InMemoryJobRepository,
    tmp_path,
):
    job = _review_gated_job("remote-with-mapping")
    portability = dict(job.meta["portability"])
    portability.update(
        {
            "source_cwd_remote_or_unverified": True,
            "source_cwd_binding": "omitted_remote_or_unverified",
        },
    )
    assert job.request is not None
    request = job.request.model_copy(
        update={
            "request_context": {
                "source": "cron",
                "portability_review_required": True,
                "project_dir": str(tmp_path),
            },
        },
    )
    job = job.model_copy(
        update={
            "meta": {"portability": portability},
            "request": request,
        },
    )
    await repo.upsert_job(job)

    promoted = await manager.promote_imported_job(job.id or "")

    assert promoted.enabled is False
    assert promoted.meta["portability"]["requires_review"] is False


@pytest.mark.asyncio
async def test_paused_job_remains_paused_after_restart(
    manager: CronManager,
    repo: InMemoryJobRepository,
):
    await manager.start()
    await manager.create_or_replace_job(make_cron_job_spec(job_id="j-restart"))
    await manager.pause_job("j-restart")
    await manager.stop()

    restarted = CronManager(
        repo=repo,
        workspace=MagicMock(),
        channel_manager=AsyncMock(),
    )
    try:
        await restarted.start()
        stored = await repo.get_job("j-restart")
        assert stored is not None
        assert stored.enabled is False
        aps_job = restarted._scheduler.get_job("j-restart")
        assert aps_job is not None
        assert aps_job.next_run_time is None
    finally:
        await restarted.stop()


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
