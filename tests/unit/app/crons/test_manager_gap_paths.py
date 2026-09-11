# -*- coding: utf-8 -*-
"""Unit tests for CronManager gap paths.

Covers the scheduler-event handlers (missed / max-instances), the
skipped-run recorder, trigger construction (once/repeat/cron/heartbeat),
the scheduled and heartbeat callbacks, service-job registration guards,
the fire-and-forget task failure callback, heartbeat rescheduling, and
the delivery-failure / exception branches of ``_execute_once``.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from apscheduler.events import (
    EVENT_JOB_MAX_INSTANCES,
    EVENT_JOB_MISSED,
    JobExecutionEvent,
    JobSubmissionEvent,
)
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from qwenpaw.app.crons.contracts import ServiceCronJob
from qwenpaw.app.crons.manager import (
    HEARTBEAT_JOB_ID,
    CronManager,
)
from qwenpaw.app.crons.models import ScheduleSpec
from qwenpaw.exceptions import ConfigurationException
from tests.unit.app.conftest import (
    InMemoryJobRepository,
    make_cron_job_spec,
)


@pytest.fixture(autouse=True)
def _no_real_inbox_writes(monkeypatch):
    """Keep cron tests from writing to the real inbox store."""
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


def _missed_event(job_id: str, run_time=None) -> JobExecutionEvent:
    if run_time is None:
        run_time = datetime.now(timezone.utc) - timedelta(minutes=5)
    return JobExecutionEvent(EVENT_JOB_MISSED, job_id, "default", run_time)


def _max_instances_event(
    job_id: str,
    times=None,
) -> JobSubmissionEvent:
    return JobSubmissionEvent(
        EVENT_JOB_MAX_INSTANCES,
        job_id,
        "default",
        times or [],
    )


# ---------------------------------------------------------------------------
# _is_internal_job / _service_job_id
# ---------------------------------------------------------------------------


class TestJobIdHelpers:
    def test_heartbeat_is_internal(self, manager):
        assert manager._is_internal_job(HEARTBEAT_JOB_ID) is True

    def test_service_prefix_is_internal(self, manager):
        assert manager._is_internal_job("_service:memory:x") is True

    def test_user_job_is_not_internal(self, manager):
        assert manager._is_internal_job("job-1") is False

    def test_service_job_id_builds_prefixed_id(self):
        assert (
            CronManager._service_job_id("memory", "compact")
            == "_service:memory:compact"
        )

    @pytest.mark.parametrize(
        ("source", "key"),
        [
            ("", "k"),
            ("s", ""),
            ("a:b", "k"),
            ("s", "a:b"),
        ],
    )
    def test_service_job_id_rejects_invalid(self, source, key):
        with pytest.raises(ValueError):
            CronManager._service_job_id(source, key)


# ---------------------------------------------------------------------------
# _now_in_job_timezone
# ---------------------------------------------------------------------------


class TestNowInJobTimezone:
    def test_valid_timezone_used(self):
        job = make_cron_job_spec()
        job.schedule.timezone = "Asia/Shanghai"
        now = CronManager._now_in_job_timezone(job)
        assert str(now.tzinfo) == "Asia/Shanghai"

    def test_invalid_timezone_falls_back_to_utc(self):
        job = make_cron_job_spec()
        job.schedule.timezone = "Not/AZone"
        now = CronManager._now_in_job_timezone(job)
        assert now.tzinfo == timezone.utc

    def test_empty_timezone_defaults_to_utc(self):
        job = make_cron_job_spec()
        job.schedule.timezone = ""
        now = CronManager._now_in_job_timezone(job)
        # Empty falls back to the "UTC" name, resolving to ZoneInfo("UTC").
        assert now.utcoffset() == timedelta(0)


# ---------------------------------------------------------------------------
# _build_trigger
# ---------------------------------------------------------------------------


class TestBuildTrigger:
    def test_once_without_repeat_builds_date_trigger(self, manager):
        job = make_cron_job_spec()
        run_at = datetime.now(timezone.utc) + timedelta(hours=1)
        job.schedule = ScheduleSpec(type="once", run_at=run_at)
        trigger = manager._build_trigger(job)
        assert isinstance(trigger, DateTrigger)

    def test_once_repeat_until_builds_interval_with_end_date(self, manager):
        job = make_cron_job_spec()
        run_at = datetime(2026, 9, 1, tzinfo=timezone.utc)
        until = datetime(2026, 9, 20, tzinfo=timezone.utc)
        job.schedule = ScheduleSpec(
            type="once",
            run_at=run_at,
            repeat_every_days=3,
            repeat_end_type="until",
            repeat_until=until,
        )
        trigger = manager._build_trigger(job)
        assert isinstance(trigger, IntervalTrigger)
        assert trigger.end_date == until

    def test_once_repeat_count_derives_end_date(self, manager):
        job = make_cron_job_spec()
        run_at = datetime(2026, 9, 1, tzinfo=timezone.utc)
        job.schedule = ScheduleSpec(
            type="once",
            run_at=run_at,
            repeat_every_days=2,
            repeat_end_type="count",
            repeat_count=4,
        )
        trigger = manager._build_trigger(job)
        assert isinstance(trigger, IntervalTrigger)
        # run_at + 2 days * (4 - 1) = run_at + 6 days
        assert trigger.end_date == run_at + timedelta(days=6)

    def test_once_repeat_never_has_no_end_date(self, manager):
        job = make_cron_job_spec()
        run_at = datetime(2026, 9, 1, tzinfo=timezone.utc)
        job.schedule = ScheduleSpec(
            type="once",
            run_at=run_at,
            repeat_every_days=5,
        )
        trigger = manager._build_trigger(job)
        assert isinstance(trigger, IntervalTrigger)
        assert trigger.end_date is None

    def test_cron_builds_cron_trigger(self, manager):
        job = make_cron_job_spec(cron="30 8 * * mon")
        trigger = manager._build_trigger(job)
        assert isinstance(trigger, CronTrigger)

    def test_cron_with_wrong_field_count_raises(self, manager):
        job = make_cron_job_spec()
        # Bypass pydantic validation so the 5-field guard inside the
        # trigger builder is what gets exercised.
        job.schedule = ScheduleSpec.model_construct(
            type="cron",
            cron="* * * * * *",
            timezone="UTC",
        )
        with pytest.raises(ConfigurationException):
            manager._build_trigger(job)


# ---------------------------------------------------------------------------
# _build_heartbeat_trigger
# ---------------------------------------------------------------------------


class TestBuildHeartbeatTrigger:
    def test_interval_string_builds_interval_trigger(self, manager):
        trigger = manager._build_heartbeat_trigger("30m")
        assert isinstance(trigger, IntervalTrigger)

    def test_cron_string_builds_cron_trigger(self, manager):
        trigger = manager._build_heartbeat_trigger("0 9 * * *")
        assert isinstance(trigger, CronTrigger)


# ---------------------------------------------------------------------------
# _record_skipped
# ---------------------------------------------------------------------------


class TestRecordSkipped:
    async def test_none_job_id_is_not_recorded(self, manager, repo):
        job = make_cron_job_spec(job_id=None)
        await manager._record_skipped(job, "some error")
        assert manager._states == {}
        assert manager._history == {}

    async def test_records_state_and_history(self, manager, repo):
        job = make_cron_job_spec(job_id="job-1")
        await repo.upsert_job(job)

        await manager._record_skipped(job, "missed the slot")

        state = manager._states["job-1"]
        assert state.last_status == "skipped"
        assert state.last_error == "missed the slot"
        records = manager._history["job-1"]
        assert len(records) == 1
        assert records[0].status == "skipped"
        assert records[0].error == "missed the slot"
        assert records[0].trigger == "scheduled"


# ---------------------------------------------------------------------------
# _handle_job_missed
# ---------------------------------------------------------------------------


class TestHandleJobMissed:
    async def test_internal_job_is_ignored(self, manager, repo):
        await manager._handle_job_missed(_missed_event(HEARTBEAT_JOB_ID))
        assert manager._states == {}

    async def test_unknown_job_is_ignored(self, manager, repo):
        await manager._handle_job_missed(_missed_event("ghost"))
        assert manager._states == {}

    async def test_missed_run_records_skip(self, manager, repo):
        job = make_cron_job_spec(job_id="job-1")
        await repo.upsert_job(job)

        await manager._handle_job_missed(_missed_event("job-1"))

        state = manager._states["job-1"]
        assert state.last_status == "skipped"
        assert "missed scheduled run" in state.last_error
        assert "grace=" in state.last_error

    async def test_naive_scheduled_time_is_treated_as_utc(
        self,
        manager,
        repo,
    ):
        job = make_cron_job_spec(job_id="job-1")
        await repo.upsert_job(job)
        naive = datetime.now() - timedelta(minutes=1)

        await manager._handle_job_missed(_missed_event("job-1", naive))

        assert manager._states["job-1"].last_status == "skipped"


# ---------------------------------------------------------------------------
# _handle_job_max_instances
# ---------------------------------------------------------------------------


class TestHandleJobMaxInstances:
    async def test_internal_job_is_ignored(self, manager, repo):
        await manager._handle_job_max_instances(
            _max_instances_event("_service:memory:x"),
        )
        assert manager._states == {}

    async def test_unknown_job_is_ignored(self, manager, repo):
        await manager._handle_job_max_instances(
            _max_instances_event("ghost"),
        )
        assert manager._states == {}

    async def test_max_instances_records_skip_with_slot_time(
        self,
        manager,
        repo,
    ):
        job = make_cron_job_spec(job_id="job-1")
        await repo.upsert_job(job)
        slot = datetime.now(timezone.utc) - timedelta(minutes=2)

        await manager._handle_job_max_instances(
            _max_instances_event("job-1", [slot]),
        )

        state = manager._states["job-1"]
        assert state.last_status == "skipped"
        assert "maximum running instances" in state.last_error
        assert slot.isoformat() in state.last_error

    async def test_max_instances_without_times_reports_unknown(
        self,
        manager,
        repo,
    ):
        job = make_cron_job_spec(job_id="job-1")
        await repo.upsert_job(job)

        await manager._handle_job_max_instances(
            _max_instances_event("job-1", []),
        )

        assert "unknown" in manager._states["job-1"].last_error

    async def test_naive_slot_time_is_treated_as_utc(self, manager, repo):
        job = make_cron_job_spec(job_id="job-1")
        await repo.upsert_job(job)
        naive = datetime.now() - timedelta(minutes=1)

        await manager._handle_job_max_instances(
            _max_instances_event("job-1", [naive]),
        )

        assert manager._states["job-1"].last_status == "skipped"


# ---------------------------------------------------------------------------
# _on_scheduler_event
# ---------------------------------------------------------------------------


class TestOnSchedulerEvent:
    async def test_missed_event_dispatches_to_handler(
        self,
        manager,
        monkeypatch,
    ):
        handler = AsyncMock()
        monkeypatch.setattr(manager, "_handle_job_missed", handler)
        event = _missed_event("job-1")

        manager._on_scheduler_event(event)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        handler.assert_awaited_once_with(event)

    async def test_max_instances_event_dispatches_to_handler(
        self,
        manager,
        monkeypatch,
    ):
        handler = AsyncMock()
        monkeypatch.setattr(manager, "_handle_job_max_instances", handler)
        event = _max_instances_event("job-1")

        manager._on_scheduler_event(event)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        handler.assert_awaited_once_with(event)


# ---------------------------------------------------------------------------
# _scheduled_callback
# ---------------------------------------------------------------------------


class TestScheduledCallback:
    async def test_missing_job_is_noop(self, manager, repo, monkeypatch):
        executor = AsyncMock()
        monkeypatch.setattr(manager._executor, "execute", executor)
        await manager._scheduled_callback("ghost")
        executor.assert_not_awaited()

    async def test_runs_job_and_refreshes_next_run(
        self,
        manager,
        repo,
        monkeypatch,
    ):
        job = make_cron_job_spec(job_id="job-1")
        await repo.upsert_job(job)
        execute = AsyncMock(
            return_value={"run_id": "r1", "delivery_status": "ok"},
        )
        monkeypatch.setattr(manager._executor, "execute", execute)

        await manager._scheduled_callback("job-1")

        execute.assert_awaited_once_with(job)
        state = manager._states["job-1"]
        # The job is not registered with the scheduler in this test, so
        # the next-run refresh resolves to None.
        assert state.next_run_at is None


# ---------------------------------------------------------------------------
# _run_service_job
# ---------------------------------------------------------------------------


class TestRunServiceJob:
    async def test_success_invokes_callback(self, manager):
        callback = AsyncMock()
        declaration = ServiceCronJob(
            key="k",
            cron="0 0 * * *",
            callback=callback,
        )
        await manager._run_service_job("memory", declaration)
        callback.assert_awaited_once()

    async def test_exception_is_swallowed(self, manager):
        callback = AsyncMock(side_effect=RuntimeError("boom"))
        declaration = ServiceCronJob(
            key="k",
            cron="0 0 * * *",
            callback=callback,
        )
        # Must not raise.
        await manager._run_service_job("memory", declaration)

    async def test_cancellation_is_propagated(self, manager):
        callback = AsyncMock(side_effect=asyncio.CancelledError)
        declaration = ServiceCronJob(
            key="k",
            cron="0 0 * * *",
            callback=callback,
        )
        with pytest.raises(asyncio.CancelledError):
            await manager._run_service_job("memory", declaration)


# ---------------------------------------------------------------------------
# _heartbeat_callback
# ---------------------------------------------------------------------------


class TestHeartbeatCallback:
    async def test_success_invokes_heartbeat_runner(
        self,
        manager,
        monkeypatch,
    ):
        runner = AsyncMock()
        monkeypatch.setattr(
            "qwenpaw.app.crons.manager.run_heartbeat_once",
            runner,
        )
        await manager._heartbeat_callback()
        runner.assert_awaited_once()
        kwargs = runner.call_args.kwargs
        assert kwargs["workspace"] is manager._workspace
        assert kwargs["channel_manager"] is manager._channel_manager
        assert kwargs["agent_id"] is manager._agent_id

    async def test_exception_is_swallowed(self, manager, monkeypatch):
        runner = AsyncMock(side_effect=RuntimeError("hb failed"))
        monkeypatch.setattr(
            "qwenpaw.app.crons.manager.run_heartbeat_once",
            runner,
        )
        # Must not raise.
        await manager._heartbeat_callback()

    async def test_cancellation_is_propagated(self, manager, monkeypatch):
        runner = AsyncMock(side_effect=asyncio.CancelledError)
        monkeypatch.setattr(
            "qwenpaw.app.crons.manager.run_heartbeat_once",
            runner,
        )
        with pytest.raises(asyncio.CancelledError):
            await manager._heartbeat_callback()


# ---------------------------------------------------------------------------
# _task_done_cb
# ---------------------------------------------------------------------------


class TestTaskDoneCb:
    async def test_cancelled_task_is_ignored(self, manager, monkeypatch):
        push = AsyncMock()
        monkeypatch.setattr(
            "qwenpaw.app.crons.manager.push_store_append",
            push,
        )

        async def sleeper():
            await asyncio.sleep(60)

        task = asyncio.create_task(sleeper())
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        manager._task_done_cb(task, make_cron_job_spec())
        await asyncio.sleep(0)
        push.assert_not_awaited()

    async def test_failed_task_pushes_error_to_console(
        self,
        manager,
        monkeypatch,
    ):
        push = AsyncMock()
        monkeypatch.setattr(
            "qwenpaw.app.crons.manager.push_store_append",
            push,
        )

        async def boom():
            raise RuntimeError("kaput")

        task = asyncio.create_task(boom())
        with pytest.raises(RuntimeError):
            await task

        job = make_cron_job_spec(name="Nightly")
        manager._task_done_cb(task, job)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        push.assert_awaited_once()
        session_id, text = push.call_args.args
        assert session_id == "console:u1"
        assert "Nightly" in text
        assert "kaput" in text

    async def test_successful_task_pushes_nothing(self, manager, monkeypatch):
        push = AsyncMock()
        monkeypatch.setattr(
            "qwenpaw.app.crons.manager.push_store_append",
            push,
        )

        async def fine():
            return None

        task = asyncio.create_task(fine())
        await task

        manager._task_done_cb(task, make_cron_job_spec())
        await asyncio.sleep(0)
        push.assert_not_awaited()


# ---------------------------------------------------------------------------
# _register_service_jobs guards
# ---------------------------------------------------------------------------


class TestRegisterServiceJobs:
    def test_invalid_key_is_skipped(self, manager):
        declaration = ServiceCronJob(
            key="bad:key",
            cron="0 0 * * *",
            callback=AsyncMock(),
        )
        manager._register_service_jobs("memory", [declaration])
        assert manager._scheduler.get_job("_service:memory:bad:key") is None

    def test_duplicate_key_registers_once(self, manager):
        callback = AsyncMock()
        first = ServiceCronJob(key="k", cron="0 0 * * *", callback=callback)
        second = ServiceCronJob(key="k", cron="0 1 * * *", callback=callback)
        manager._register_service_jobs("memory", [first, second])
        job = manager._scheduler.get_job("_service:memory:k")
        assert job is not None

    def test_invalid_cron_is_skipped(self, manager):
        declaration = ServiceCronJob(
            key="k",
            cron="not a cron",
            callback=AsyncMock(),
        )
        manager._register_service_jobs("memory", [declaration])
        assert manager._scheduler.get_job("_service:memory:k") is None

    def test_valid_declaration_is_registered(self, manager):
        declaration = ServiceCronJob(
            key="compact",
            cron="0 3 * * *",
            callback=AsyncMock(),
        )
        manager._register_service_jobs("memory", [declaration])
        job = manager._scheduler.get_job("_service:memory:compact")
        assert job is not None

    def test_memory_manager_without_jobs_registers_nothing(self, manager):
        manager._workspace.memory_manager = None
        manager._register_memory_jobs()
        # Nothing scheduled and no exception raised.
        assert manager._scheduler.get_jobs() == []

    def test_memory_manager_listing_failure_is_tolerated(self, manager):
        manager._workspace.memory_manager.list_cron_jobs.side_effect = (
            RuntimeError("db down")
        )
        # Must not raise.
        manager._register_memory_jobs()
        assert manager._scheduler.get_jobs() == []


# ---------------------------------------------------------------------------
# reschedule_heartbeat
# ---------------------------------------------------------------------------


class TestRescheduleHeartbeat:
    async def test_not_started_is_noop(self, manager, monkeypatch):
        config = SimpleNamespace(enabled=True, every="30m")
        monkeypatch.setattr(
            "qwenpaw.app.crons.manager.get_heartbeat_config",
            lambda agent_id: config,
        )
        await manager.reschedule_heartbeat()
        assert manager._scheduler.get_job(HEARTBEAT_JOB_ID) is None

    async def test_enabled_heartbeat_is_added(self, manager, monkeypatch):
        manager._started = True
        config = SimpleNamespace(enabled=True, every="30m")
        monkeypatch.setattr(
            "qwenpaw.app.crons.manager.get_heartbeat_config",
            lambda agent_id: config,
        )
        await manager.reschedule_heartbeat()
        job = manager._scheduler.get_job(HEARTBEAT_JOB_ID)
        assert job is not None
        assert isinstance(job.trigger, IntervalTrigger)

    async def test_disabled_heartbeat_removes_existing_job(
        self,
        manager,
        monkeypatch,
    ):
        manager._started = True
        enabled = SimpleNamespace(enabled=True, every="30m")
        monkeypatch.setattr(
            "qwenpaw.app.crons.manager.get_heartbeat_config",
            lambda agent_id: enabled,
        )
        await manager.reschedule_heartbeat()
        assert manager._scheduler.get_job(HEARTBEAT_JOB_ID) is not None

        disabled = SimpleNamespace(enabled=False, every="30m")
        monkeypatch.setattr(
            "qwenpaw.app.crons.manager.get_heartbeat_config",
            lambda agent_id: disabled,
        )
        await manager.reschedule_heartbeat()
        assert manager._scheduler.get_job(HEARTBEAT_JOB_ID) is None

    async def test_cron_heartbeat_uses_cron_trigger(
        self,
        manager,
        monkeypatch,
    ):
        manager._started = True
        config = SimpleNamespace(enabled=True, every="0 9 * * *")
        monkeypatch.setattr(
            "qwenpaw.app.crons.manager.get_heartbeat_config",
            lambda agent_id: config,
        )
        await manager.reschedule_heartbeat()
        job = manager._scheduler.get_job(HEARTBEAT_JOB_ID)
        assert isinstance(job.trigger, CronTrigger)


# ---------------------------------------------------------------------------
# _execute_once remaining branches
# ---------------------------------------------------------------------------


class TestExecuteOnceBranches:
    async def test_delivery_failure_marks_error_and_fallback_event(
        self,
        manager,
        repo,
        monkeypatch,
    ):
        job = make_cron_job_spec(job_id="job-1")
        await repo.upsert_job(job)
        execute = AsyncMock(
            return_value={
                "run_id": "r1",
                "delivery_status": "failed",
                "delivery_error": "channel down",
            },
        )
        monkeypatch.setattr(manager._executor, "execute", execute)
        inbox = AsyncMock()
        monkeypatch.setattr(
            "qwenpaw.app.crons.manager.append_inbox_event",
            inbox,
        )

        await manager._execute_once(job, trigger="manual")

        state = manager._states["job-1"]
        assert state.last_status == "error"
        assert "channel down" in state.last_error
        records = manager._history["job-1"]
        assert records[0].status == "error"
        assert records[0].trigger == "manual"
        inbox.assert_awaited_once()
        kwargs = inbox.call_args.kwargs
        assert kwargs["event_type"] == "cron_delivery_failed_fallback"
        assert kwargs["payload"]["delivery_error"] == "channel down"

    async def test_execution_exception_marks_error_and_reraises(
        self,
        manager,
        repo,
        monkeypatch,
    ):
        job = make_cron_job_spec(job_id="job-1")
        await repo.upsert_job(job)
        execute = AsyncMock(side_effect=ValueError("executor blew up"))
        monkeypatch.setattr(manager._executor, "execute", execute)

        with pytest.raises(ValueError):
            await manager._execute_once(job)

        state = manager._states["job-1"]
        assert state.last_status == "error"
        assert "executor blew up" in state.last_error
        records = manager._history["job-1"]
        assert records[0].status == "error"

    async def test_success_with_inbox_save_appends_result_event(
        self,
        manager,
        repo,
        monkeypatch,
    ):
        job = make_cron_job_spec(job_id="job-1", task_type="text")
        job.save_result_to_inbox = True
        await repo.upsert_job(job)
        execute = AsyncMock(
            return_value={"run_id": "r1", "delivery_status": "ok"},
        )
        monkeypatch.setattr(manager._executor, "execute", execute)
        inbox = AsyncMock()
        monkeypatch.setattr(
            "qwenpaw.app.crons.manager.append_inbox_event",
            inbox,
        )

        await manager._execute_once(job)

        state = manager._states["job-1"]
        assert state.last_status == "success"
        assert state.last_error is None
        inbox.assert_awaited_once()
        kwargs = inbox.call_args.kwargs
        assert kwargs["event_type"] == "cron_result"
        assert kwargs["body"] == "Hello"
