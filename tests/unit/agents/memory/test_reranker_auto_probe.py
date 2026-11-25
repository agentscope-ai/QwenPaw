# -*- coding: utf-8 -*-
"""Regression tests for ReMe-scoped reranker auto-verification and cooldown."""

import secrets
import time
from collections.abc import Iterator
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from qwenpaw.agents.memory import reranker_auto_probe as module
from qwenpaw.agents.memory.base_memory_manager import BaseMemoryManager
from qwenpaw.agents.memory.reme_light_memory_manager import (
    ReMeLightMemoryManager,
)
from qwenpaw.agents.memory.reranker_history import RerankerHistoryRecord
from qwenpaw.config.config import (
    AgentProfileConfig,
    AgentsRunningConfig,
    ReMeLightMemoryConfig,
    RerankerConfig,
)

_TEST_BASE_URL = "https://api.example.com/v1"


@pytest.fixture(autouse=True)
def _reset_attempt_timestamps() -> Iterator[None]:
    module.clear_attempt_timestamps()
    yield
    module.clear_attempt_timestamps()


def _reranker(**overrides) -> RerankerConfig:
    values = {
        "enabled": True,
        "api_key": f"probe-{secrets.token_hex(12)}",
        "base_url": _TEST_BASE_URL,
        "model_name": "probe-reranker",
        "auto_verify_interval_hours": 24,
    }
    values.update(overrides)
    return RerankerConfig(**values)


def _agent_config(reranker: RerankerConfig | None) -> AgentProfileConfig:
    """Build the real profile model with the runtime nesting."""
    return AgentProfileConfig(
        id="default",
        name="Default",
        running=AgentsRunningConfig(
            reme_light_memory_config=ReMeLightMemoryConfig(
                reranker_config=reranker or RerankerConfig(),
            ),
        ),
    )


def _probe_environment(
    reranker: RerankerConfig | None,
    probe,
    *,
    history: list[RerankerHistoryRecord] | None = None,
    appended: list[RerankerHistoryRecord] | None = None,
) -> ExitStack:
    """Patch collaborators reached by probe_agent_reranker_if_due."""
    stack = ExitStack()
    stack.enter_context(
        patch(
            "qwenpaw.config.config.load_agent_config",
            return_value=_agent_config(reranker),
        ),
    )
    stack.enter_context(
        patch(
            "qwenpaw.agents.memory.reme_reranker.test_reranker_model",
            probe,
        ),
    )
    stack.enter_context(
        patch(
            "qwenpaw.agents.memory.reranker_history.get_history",
            return_value=history or [],
        ),
    )
    sink = appended if appended is not None else []

    def _append(_fingerprint, record):
        sink.append(record)
        return list(sink)

    stack.enter_context(
        patch(
            "qwenpaw.agents.memory.reranker_history.append_record",
            side_effect=_append,
        ),
    )
    return stack


_SUCCESS = SimpleNamespace(
    success=True,
    latency_ms=12,
    precision=1.0,
    correct_count=5,
    total=5,
    message="ok",
)

_FAILURE = SimpleNamespace(
    success=False,
    latency_ms=5,
    precision=None,
    correct_count=0,
    total=0,
    message="boom",
)


def _reme_manager_with_reranker(
    reranker: RerankerConfig | None,
    *,
    started: bool = True,
) -> ReMeLightMemoryManager:
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager.agent_id = "default"
    manager._reme = SimpleNamespace(is_started=started) if started else None
    manager._load_memory_config = lambda: ReMeLightMemoryConfig(
        reranker_config=reranker or RerankerConfig(),
    )
    return manager


def test_reme_declares_reranker_job_only_when_active_and_enabled() -> None:
    """Auto-verification is tied to an active ReMe workspace via
    ServiceCronJob, so disabled agents and non-ReMe backends never schedule it.
    """
    manager = _reme_manager_with_reranker(_reranker())

    jobs = manager.list_cron_jobs()
    matching = [job for job in jobs if job.key == "reranker-auto-verify"]

    assert len(matching) == 1
    assert matching[0].cron == module.RERANKER_AUTO_VERIFY_CRON
    assert matching[0].callback == manager._run_reranker_auto_probe


def test_reme_omits_reranker_job_when_stopped_disabled_or_zero_interval() -> (
    None
):
    stopped = _reme_manager_with_reranker(_reranker(), started=False)
    disabled = _reme_manager_with_reranker(_reranker(enabled=False))
    zero_interval = _reme_manager_with_reranker(
        _reranker(auto_verify_interval_hours=0),
    )
    no_url = _reme_manager_with_reranker(_reranker(base_url=""))

    for manager in (stopped, disabled, zero_interval, no_url):
        assert [
            job for job in manager.list_cron_jobs() if "reranker" in job.key
        ] == []


def test_non_reme_memory_manager_declares_no_reranker_job() -> None:
    """An enabled agent switched away from ReMe uses another memory manager and
    must never declare or run reranker auto-verification."""

    class _OtherMemoryManager(BaseMemoryManager):
        async def start(self) -> None:
            return None

        async def auto_memory(self, *args, **kwargs):
            return None

        async def memory_search(self, *args, **kwargs):
            return None

    other_manager = _OtherMemoryManager.__new__(_OtherMemoryManager)
    assert other_manager.list_cron_jobs() == []


@pytest.mark.asyncio
async def test_cron_manager_schedules_reranker_job_only_for_reme(
    tmp_path,
) -> None:
    """CronManager registers the reranker auto-verify job only when the active
    workspace runs ReMe with reranker auto-verification enabled."""
    from unittest.mock import MagicMock

    from qwenpaw.app.crons.manager import CronManager
    from qwenpaw.app.crons.repo.json_repo import JsonJobRepository

    reme_ws = MagicMock()
    reme_ws.memory_manager = _reme_manager_with_reranker(_reranker())
    reme_cron = CronManager(
        repo=JsonJobRepository(tmp_path / "reme_jobs.json"),
        workspace=reme_ws,
        channel_manager=AsyncMock(),
        agent_id="reme-agent",
    )
    await reme_cron.start()
    try:
        assert (
            reme_cron._scheduler.get_job(
                "_service:memory:reranker-auto-verify",
            )
            is not None
        )
    finally:
        await reme_cron.stop()

    class _OtherMemoryManager(BaseMemoryManager):
        async def start(self) -> None:
            return None

        async def auto_memory(self, *args, **kwargs):
            return None

        async def memory_search(self, *args, **kwargs):
            return None

    other_ws = MagicMock()
    other_ws.memory_manager = _OtherMemoryManager.__new__(_OtherMemoryManager)
    other_cron = CronManager(
        repo=JsonJobRepository(tmp_path / "other_jobs.json"),
        workspace=other_ws,
        channel_manager=AsyncMock(),
        agent_id="non-reme-agent",
    )
    await other_cron.start()
    try:
        assert (
            other_cron._scheduler.get_job(
                "_service:memory:reranker-auto-verify",
            )
            is None
        )
    finally:
        await other_cron.stop()


@pytest.mark.asyncio
async def test_reme_callback_skips_when_stopped() -> None:
    manager = _reme_manager_with_reranker(_reranker(), started=False)
    probe = AsyncMock(return_value=_SUCCESS)
    with _probe_environment(_reranker(), probe):
        await manager._run_reranker_auto_probe()

    assert probe.await_count == 0


@pytest.mark.asyncio
async def test_probe_reaches_service_through_running_memory_config() -> None:
    """The scheduled callback reads reranker_config from
    running.reme_light_memory_config and probes local/private targets."""
    probe = AsyncMock(return_value=_SUCCESS)
    appended: list[RerankerHistoryRecord] = []
    with _probe_environment(_reranker(), probe, appended=appended):
        outcome = await module.probe_agent_reranker_if_due("default")

    assert outcome is not None
    assert probe.await_count == 1
    assert probe.await_args.kwargs["allow_private"] is True
    assert len(appended) == 1
    assert appended[0].precision == 1.0
    assert appended[0].total == 5


@pytest.mark.asyncio
async def test_probe_skips_when_reranker_missing() -> None:
    probe = AsyncMock()
    with _probe_environment(None, probe):
        outcome = await module.probe_agent_reranker_if_due("default")

    assert outcome is None
    assert probe.await_count == 0


@pytest.mark.asyncio
async def test_probe_skips_when_interval_is_zero() -> None:
    probe = AsyncMock()
    with _probe_environment(_reranker(auto_verify_interval_hours=0), probe):
        outcome = await module.probe_agent_reranker_if_due("default")

    assert outcome is None
    assert probe.await_count == 0


@pytest.mark.asyncio
async def test_probe_skips_when_history_interval_has_not_elapsed() -> None:
    probe = AsyncMock()
    recent = [RerankerHistoryRecord(ts=int((time.time() - 3600) * 1000))]
    with _probe_environment(_reranker(), probe, history=recent):
        outcome = await module.probe_agent_reranker_if_due("default")

    assert outcome is None
    assert probe.await_count == 0


@pytest.mark.asyncio
async def test_failed_probe_waits_full_configured_interval_before_retry() -> (
    None
):
    """A failed probe must not remain due on the next 30-minute tick; a 24h
    interval must wait 24h from the last attempt."""
    reranker = _reranker(auto_verify_interval_hours=24)
    probe = AsyncMock(return_value=_FAILURE)
    appended: list[RerankerHistoryRecord] = []
    t0 = 1_700_000_000.0

    with _probe_environment(reranker, probe, appended=appended):
        first = await module.probe_agent_reranker_if_due("default", now=t0)
        # 30 minutes later: still within the 24h cooldown from the failed run.
        second = await module.probe_agent_reranker_if_due(
            "default",
            now=t0 + 1800.0,
        )
        # 23 hours later: still within cooldown.
        third = await module.probe_agent_reranker_if_due(
            "default",
            now=t0 + 23 * 3600.0,
        )
        # 24 hours later: due again.
        fourth = await module.probe_agent_reranker_if_due(
            "default",
            now=t0 + 24 * 3600.0,
        )

    assert first is not None and first.result.success is False
    assert second is None
    assert third is None
    assert fourth is not None
    assert probe.await_count == 2
    assert appended == []


@pytest.mark.asyncio
async def test_probe_and_record_separates_history_write_error() -> None:
    reranker = _reranker()
    probe = AsyncMock(return_value=_SUCCESS)
    with (
        patch(
            "qwenpaw.agents.memory.reme_reranker.test_reranker_model",
            probe,
        ),
        patch(
            "qwenpaw.agents.memory.reranker_history.append_record",
            side_effect=OSError("read-only filesystem"),
        ),
    ):
        outcome = await module.probe_and_record(reranker, allow_private=True)

    assert outcome.result.success is True
    assert outcome.history is None
    assert outcome.history_error is not None
    assert "read-only filesystem" in outcome.history_error
