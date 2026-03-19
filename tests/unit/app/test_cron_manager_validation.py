# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import importlib
import sys
import types

from copaw.app.crons.models import CronJobSpec, JobsFile


MANAGER_MODULE = "copaw.app.crons.manager"
API_MODULE = "copaw.app.crons.api"


class InMemoryJobRepository:
    def __init__(self, jobs: list[CronJobSpec] | None = None) -> None:
        self.jobs = list(jobs or [])
        self.upsert_calls = 0
        self.save_calls = 0

    async def load(self) -> JobsFile:
        return JobsFile(jobs=list(self.jobs))

    async def save(self, jobs_file: JobsFile) -> None:
        self.save_calls += 1
        self.jobs = list(jobs_file.jobs)

    async def list_jobs(self) -> list[CronJobSpec]:
        return list(self.jobs)

    async def get_job(self, job_id: str) -> CronJobSpec | None:
        for job in self.jobs:
            if job.id == job_id:
                return job
        return None

    async def upsert_job(self, spec: CronJobSpec) -> None:
        self.upsert_calls += 1
        for index, job in enumerate(self.jobs):
            if job.id == spec.id:
                self.jobs[index] = spec
                break
        else:
            self.jobs.append(spec)

    async def delete_job(self, job_id: str) -> bool:
        before = len(self.jobs)
        self.jobs = [job for job in self.jobs if job.id != job_id]
        return len(self.jobs) != before


class FakeCronTrigger:
    def __init__(self, **kwargs) -> None:
        hour = kwargs.get("hour")
        if hour == "*/30":
            raise ValueError(
                "Error validating expression '*/30': the step value (30) is higher than the total range of the expression (23)",
            )
        self.kwargs = kwargs


class FakeIntervalTrigger:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs


class FakeSchedulerJob:
    def __init__(self, trigger) -> None:
        self.trigger = trigger
        self.next_run_time = "fake-next-run"
        self.paused = False


class FakeAsyncIOScheduler:
    def __init__(self, timezone: str = "UTC") -> None:
        self.timezone = timezone
        self.jobs: dict[str, FakeSchedulerJob] = {}
        self.started = False
        self.shutdown_called = False

    def start(self) -> None:
        self.started = True

    def shutdown(self, wait: bool = False) -> None:
        self.shutdown_called = True

    def add_job(
        self,
        func,
        trigger=None,
        id: str | None = None,
        args=None,
        misfire_grace_time=None,
        replace_existing: bool = False,
    ) -> None:
        if id is None:
            raise ValueError("job id required")
        self.jobs[id] = FakeSchedulerJob(trigger)

    def get_job(self, job_id: str):
        return self.jobs.get(job_id)

    def remove_job(self, job_id: str) -> None:
        self.jobs.pop(job_id, None)

    def pause_job(self, job_id: str) -> None:
        self.jobs[job_id].paused = True

    def resume_job(self, job_id: str) -> None:
        self.jobs[job_id].paused = False


def _install_manager_stubs() -> None:
    config_module = types.ModuleType("copaw.config")
    config_module.get_heartbeat_config = lambda: types.SimpleNamespace(enabled=False, every="6h")
    sys.modules["copaw.config"] = config_module

    console_push_store = types.ModuleType("copaw.app.console_push_store")

    async def _append(session_id: str, text: str) -> None:
        return None

    console_push_store.append = _append
    sys.modules["copaw.app.console_push_store"] = console_push_store

    executor_module = types.ModuleType("copaw.app.crons.executor")

    class _CronExecutor:
        def __init__(self, runner, channel_manager) -> None:
            self.runner = runner
            self.channel_manager = channel_manager

        async def execute(self, job) -> None:
            return None

    executor_module.CronExecutor = _CronExecutor
    sys.modules["copaw.app.crons.executor"] = executor_module

    heartbeat_module = types.ModuleType("copaw.app.crons.heartbeat")
    heartbeat_module.parse_heartbeat_every = lambda every: 60

    async def _run_heartbeat_once(runner, channel_manager) -> None:
        return None

    heartbeat_module.run_heartbeat_once = _run_heartbeat_once
    sys.modules["copaw.app.crons.heartbeat"] = heartbeat_module

    apscheduler_module = types.ModuleType("apscheduler")
    sys.modules["apscheduler"] = apscheduler_module

    schedulers_module = types.ModuleType("apscheduler.schedulers")
    sys.modules["apscheduler.schedulers"] = schedulers_module

    schedulers_asyncio_module = types.ModuleType("apscheduler.schedulers.asyncio")
    schedulers_asyncio_module.AsyncIOScheduler = FakeAsyncIOScheduler
    sys.modules["apscheduler.schedulers.asyncio"] = schedulers_asyncio_module

    triggers_module = types.ModuleType("apscheduler.triggers")
    sys.modules["apscheduler.triggers"] = triggers_module

    triggers_cron_module = types.ModuleType("apscheduler.triggers.cron")
    triggers_cron_module.CronTrigger = FakeCronTrigger
    sys.modules["apscheduler.triggers.cron"] = triggers_cron_module

    triggers_interval_module = types.ModuleType("apscheduler.triggers.interval")
    triggers_interval_module.IntervalTrigger = FakeIntervalTrigger
    sys.modules["apscheduler.triggers.interval"] = triggers_interval_module


def _load_manager_module():
    _install_manager_stubs()
    sys.modules.pop(MANAGER_MODULE, None)
    return importlib.import_module(MANAGER_MODULE)


def _install_fastapi_stub() -> None:
    fastapi_module = types.ModuleType("fastapi")

    class HTTPException(Exception):
        def __init__(self, status_code: int, detail: str) -> None:
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    class APIRouter:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

        def _decorator(self, *args, **kwargs):
            def wrapper(fn):
                return fn

            return wrapper

        get = post = put = delete = _decorator

    def Depends(fn):
        return fn

    class Request:
        pass

    fastapi_module.APIRouter = APIRouter
    fastapi_module.Depends = Depends
    fastapi_module.HTTPException = HTTPException
    fastapi_module.Request = Request
    sys.modules["fastapi"] = fastapi_module


def _load_api_module():
    _install_manager_stubs()
    _install_fastapi_stub()
    sys.modules.pop(MANAGER_MODULE, None)
    sys.modules.pop(API_MODULE, None)
    return importlib.import_module(API_MODULE)


def _make_job(job_id: str, cron: str) -> CronJobSpec:
    return CronJobSpec.model_validate(
        {
            "id": job_id,
            "name": f"job-{job_id}",
            "enabled": True,
            "schedule": {
                "type": "cron",
                "cron": cron,
                "timezone": "UTC",
            },
            "task_type": "text",
            "text": "hello",
            "dispatch": {
                "type": "channel",
                "channel": "console",
                "target": {
                    "user_id": "user-1",
                    "session_id": "session-1",
                },
                "mode": "final",
                "meta": {},
            },
            "runtime": {
                "max_concurrency": 1,
                "timeout_seconds": 120,
                "misfire_grace_seconds": 60,
            },
            "meta": {},
        },
    )


def test_start_skips_invalid_persisted_job_and_keeps_valid_jobs() -> None:
    manager_module = _load_manager_module()
    repo = InMemoryJobRepository(
        jobs=[
            _make_job("bad", "0 */30 8-18 * 1-5"),
            _make_job("good", "0 9 * * 1-5"),
        ],
    )
    manager = manager_module.CronManager(
        repo=repo,
        runner=object(),
        channel_manager=object(),
    )

    asyncio.run(manager.start())

    bad_state = manager.get_state("bad")
    good_state = manager.get_state("good")

    assert manager._started is True
    assert bad_state.last_status == "error"
    assert "step value (30)" in (bad_state.last_error or "")
    assert bad_state.next_run_at is None
    assert "bad" not in manager._scheduler.jobs
    assert "bad" not in manager._rt
    assert "good" in manager._scheduler.jobs
    assert good_state.next_run_at == "fake-next-run"


def test_create_or_replace_job_rejects_invalid_schedule_before_persisting() -> None:
    manager_module = _load_manager_module()
    repo = InMemoryJobRepository()
    manager = manager_module.CronManager(
        repo=repo,
        runner=object(),
        channel_manager=object(),
    )

    try:
        asyncio.run(
            manager.create_or_replace_job(
                _make_job("bad", "0 */30 8-18 * 1-5"),
            ),
        )
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected invalid cron schedule to raise ValueError")

    assert "step value (30)" in message
    assert repo.upsert_calls == 0
    assert repo.jobs == []


def test_create_or_replace_job_persists_and_registers_valid_schedule() -> None:
    manager_module = _load_manager_module()
    repo = InMemoryJobRepository()
    manager = manager_module.CronManager(
        repo=repo,
        runner=object(),
        channel_manager=object(),
    )
    asyncio.run(manager.start())

    spec = _make_job("good", "0 9 * * 1-5")
    asyncio.run(manager.create_or_replace_job(spec))

    assert repo.upsert_calls == 1
    assert repo.jobs[0].id == "good"
    assert "good" in manager._scheduler.jobs
    assert manager.get_state("good").next_run_at == "fake-next-run"


def test_create_job_returns_http_400_for_invalid_schedule() -> None:
    api_module = _load_api_module()
    http_exception_type = sys.modules["fastapi"].HTTPException

    class FailingManager:
        async def create_or_replace_job(self, spec) -> None:
            raise ValueError("invalid cron")

    try:
        asyncio.run(
            api_module.create_job(
                spec=_make_job("ignored", "0 9 * * 1-5"),
                mgr=FailingManager(),
            ),
        )
    except http_exception_type as exc:
        error = exc
    else:
        raise AssertionError("Expected create_job to translate ValueError into HTTPException")

    assert error.status_code == 400
    assert error.detail == "invalid cron"


def test_replace_job_returns_http_400_for_invalid_schedule() -> None:
    api_module = _load_api_module()
    http_exception_type = sys.modules["fastapi"].HTTPException

    class FailingManager:
        async def create_or_replace_job(self, spec) -> None:
            raise ValueError("invalid cron")

    spec = _make_job("job-1", "0 9 * * 1-5")
    try:
        asyncio.run(
            api_module.replace_job(
                job_id="job-1",
                spec=spec,
                mgr=FailingManager(),
            ),
        )
    except http_exception_type as exc:
        error = exc
    else:
        raise AssertionError("Expected replace_job to translate ValueError into HTTPException")

    assert error.status_code == 400
    assert error.detail == "invalid cron"
