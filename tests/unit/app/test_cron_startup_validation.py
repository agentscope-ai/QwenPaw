# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib
import sys
import types
from datetime import datetime
import pytest

from copaw.app.crons.models import CronJobSpec, JobsFile
from copaw.app.crons.repo.base import BaseJobRepository


class InMemoryJobRepository(BaseJobRepository):
    def __init__(self, jobs: list[CronJobSpec] | None = None):
        self._jobs_file = JobsFile(version=1, jobs=list(jobs or []))

    async def load(self) -> JobsFile:
        return self._jobs_file.model_copy(deep=True)

    async def save(self, jobs_file: JobsFile) -> None:
        self._jobs_file = jobs_file.model_copy(deep=True)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


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
        },
    )


def _install_apscheduler_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    apscheduler_module = types.ModuleType("apscheduler")
    schedulers_module = types.ModuleType("apscheduler.schedulers")
    asyncio_module = types.ModuleType("apscheduler.schedulers.asyncio")
    triggers_module = types.ModuleType("apscheduler.triggers")
    cron_module = types.ModuleType("apscheduler.triggers.cron")
    interval_module = types.ModuleType("apscheduler.triggers.interval")

    class _ScheduledJob:
        def __init__(self, job_id: str):
            self.id = job_id
            self.next_run_time = datetime.utcnow()

    class AsyncIOScheduler:
        def __init__(self, timezone: str):
            self.timezone = timezone
            self._jobs: dict[str, _ScheduledJob] = {}

        def start(self) -> None:
            return None

        def shutdown(self, wait: bool = False) -> None:
            return None

        def add_job(
            self,
            func,
            trigger,
            *,
            id: str,
            replace_existing: bool = False,
            args=None,
            misfire_grace_time=None,
        ) -> None:
            self._jobs[id] = _ScheduledJob(id)

        def get_job(self, job_id: str):
            return self._jobs.get(job_id)

        def remove_job(self, job_id: str) -> None:
            self._jobs.pop(job_id, None)

        def pause_job(self, job_id: str) -> None:
            if job_id in self._jobs:
                self._jobs[job_id].next_run_time = None

        def resume_job(self, job_id: str) -> None:
            if job_id in self._jobs:
                self._jobs[job_id].next_run_time = datetime.utcnow()

    class CronTrigger:
        def __init__(
            self,
            *,
            minute: str,
            hour: str,
            day: str,
            month: str,
            day_of_week: str,
            timezone: str,
        ):
            self.minute = minute
            self.hour = hour
            self.day = day
            self.month = month
            self.day_of_week = day_of_week
            self.timezone = timezone
            self._validate_step(minute, 59)
            self._validate_step(hour, 23)
            self._validate_step(day, 31)
            self._validate_step(month, 12)
            self._validate_step(day_of_week, 6)

        @staticmethod
        def _validate_step(expr: str, total_range: int) -> None:
            if expr.startswith("*/"):
                step = int(expr[2:])
                if step > total_range:
                    raise ValueError(
                        "Error validating expression "
                        f"'{expr}': the step value ({step}) is higher than "
                        f"the total range of the expression ({total_range})",
                    )

    class IntervalTrigger:
        def __init__(self, *, seconds: int):
            self.seconds = seconds

    asyncio_module.AsyncIOScheduler = AsyncIOScheduler
    cron_module.CronTrigger = CronTrigger
    interval_module.IntervalTrigger = IntervalTrigger

    monkeypatch.setitem(sys.modules, "apscheduler", apscheduler_module)
    monkeypatch.setitem(sys.modules, "apscheduler.schedulers", schedulers_module)
    monkeypatch.setitem(sys.modules, "apscheduler.schedulers.asyncio", asyncio_module)
    monkeypatch.setitem(sys.modules, "apscheduler.triggers", triggers_module)
    monkeypatch.setitem(sys.modules, "apscheduler.triggers.cron", cron_module)
    monkeypatch.setitem(sys.modules, "apscheduler.triggers.interval", interval_module)


def _load_manager_module(monkeypatch: pytest.MonkeyPatch):
    _install_apscheduler_stub(monkeypatch)
    sys.modules.pop("copaw.app.crons.manager", None)
    return importlib.import_module("copaw.app.crons.manager")


def _make_manager(manager_module, repo: BaseJobRepository):
    return manager_module.CronManager(
        repo=repo,
        runner=object(),
        channel_manager=object(),
        timezone="UTC",
    )


def _load_cron_api_module(monkeypatch: pytest.MonkeyPatch):
    _install_apscheduler_stub(monkeypatch)
    fastapi_stub = types.ModuleType("fastapi")

    class HTTPException(Exception):
        def __init__(self, status_code: int, detail: str):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    class APIRouter:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def get(self, *args, **kwargs):
            return self._decorator()

        def post(self, *args, **kwargs):
            return self._decorator()

        def put(self, *args, **kwargs):
            return self._decorator()

        def delete(self, *args, **kwargs):
            return self._decorator()

        @staticmethod
        def _decorator():
            def wrapper(func):
                return func

            return wrapper

    def Depends(dependency):
        return dependency

    class Request:  # pragma: no cover - only for import compatibility
        pass

    fastapi_stub.APIRouter = APIRouter
    fastapi_stub.Depends = Depends
    fastapi_stub.HTTPException = HTTPException
    fastapi_stub.Request = Request

    monkeypatch.setitem(sys.modules, "fastapi", fastapi_stub)
    sys.modules.pop("copaw.app.crons.manager", None)
    sys.modules.pop("copaw.app.crons.api", None)
    return importlib.import_module("copaw.app.crons.api")


@pytest.mark.anyio
async def test_start_skips_invalid_persisted_job_and_marks_state_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    valid = _make_job("valid", "0 8 * * 1-5")
    invalid = _make_job("invalid", "0 */30 8-18 * 1-5")
    repo = InMemoryJobRepository([valid, invalid])
    manager_module = _load_manager_module(monkeypatch)
    manager = _make_manager(manager_module, repo)

    try:
        await manager.start()

        assert manager._scheduler.get_job(valid.id) is not None
        assert manager._scheduler.get_job(invalid.id) is None

        state = manager.get_state(invalid.id)
        assert state.last_status == "error"
        assert state.next_run_at is None
        assert "step value" in (state.last_error or "")
    finally:
        await manager.stop()


@pytest.mark.anyio
async def test_create_or_replace_job_rejects_invalid_cron_without_persisting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = InMemoryJobRepository()
    manager_module = _load_manager_module(monkeypatch)
    manager = _make_manager(manager_module, repo)

    with pytest.raises(ValueError, match="step value"):
        await manager.create_or_replace_job(_make_job("bad", "0 */30 8-18 * 1-5"))

    assert await repo.list_jobs() == []


@pytest.mark.anyio
async def test_create_job_returns_400_for_invalid_semantic_cron(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_module = _load_cron_api_module(monkeypatch)
    manager = _make_manager(api_module, InMemoryJobRepository())
    spec = _make_job("client-id", "0 */30 8-18 * 1-5")

    with pytest.raises(api_module.HTTPException) as exc:
        await api_module.create_job(spec, mgr=manager)

    assert exc.value.status_code == 400
    assert "step value" in exc.value.detail


@pytest.mark.anyio
async def test_replace_job_returns_400_for_invalid_semantic_cron(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_module = _load_cron_api_module(monkeypatch)
    manager = _make_manager(api_module, InMemoryJobRepository())
    spec = _make_job("job-1", "0 */30 8-18 * 1-5")

    with pytest.raises(api_module.HTTPException) as exc:
        await api_module.replace_job("job-1", spec, mgr=manager)

    assert exc.value.status_code == 400
    assert "step value" in exc.value.detail
