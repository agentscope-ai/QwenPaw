# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

exc_mod = types.ModuleType("agentscope_runtime.engine.schemas.exception")


class ConfigurationException(Exception):
    def __init__(self, message: str = "") -> None:
        super().__init__(message)
        self.message = message


exc_mod.ConfigurationException = ConfigurationException
sys.modules.setdefault("agentscope_runtime", types.ModuleType("agentscope_runtime"))
sys.modules.setdefault(
    "agentscope_runtime.engine",
    types.ModuleType("agentscope_runtime.engine"),
)
sys.modules.setdefault(
    "agentscope_runtime.engine.schemas",
    types.ModuleType("agentscope_runtime.engine.schemas"),
)
sys.modules["agentscope_runtime.engine.schemas.exception"] = exc_mod

from qwenpaw.app.crons.executor import CronExecutor
from qwenpaw.app.crons.models import CronJobSpec


class DummyRunner:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    async def stream_query(self, req: dict[str, Any]):
        self.requests.append(req)
        yield {"type": "message", "text": "ok"}


class DummyChannelManager:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.texts: list[dict[str, Any]] = []

    async def send_event(self, **kwargs):
        self.events.append(kwargs)

    async def send_text(self, **kwargs):
        self.texts.append(kwargs)


def make_agent_job(mode: str = "dispatch") -> CronJobSpec:
    return CronJobSpec.model_validate(
        {
            "id": "job-1",
            "name": "Job 1",
            "enabled": True,
            "schedule": {"type": "cron", "cron": "0 9 * * *", "timezone": "UTC"},
            "task_type": "agent",
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
            "dispatch": {
                "type": "channel",
                "channel": "console",
                "target": {"user_id": "target-user", "session_id": "target-session"},
                "mode": "final",
                "meta": {},
            },
            "execution": {"session": {"mode": mode}},
            "runtime": {
                "max_concurrency": 1,
                "timeout_seconds": 30,
                "misfire_grace_seconds": 60,
            },
            "meta": {},
        }
    )


def test_cron_executor_dispatch_mode_reuses_target_session() -> None:
    async def _run() -> None:
        runner = DummyRunner()
        channel_manager = DummyChannelManager()
        executor = CronExecutor(runner=runner, channel_manager=channel_manager)

        await executor.execute(make_agent_job("dispatch"))

        assert len(runner.requests) == 1
        assert runner.requests[0]["session_id"] == "target-session"
        assert runner.requests[0]["user_id"] == "target-user"

        assert len(channel_manager.events) == 1
        event_call = channel_manager.events[0]
        assert event_call["session_id"] == "target-session"
        assert event_call["meta"]["execution_session_id"] == "target-session"
        assert event_call["meta"]["dispatch_session_id"] == "target-session"
        assert event_call["meta"]["session_mode"] == "dispatch"

    asyncio.run(_run())


def test_cron_executor_new_per_run_uses_fresh_execution_session() -> None:
    async def _run() -> None:
        runner = DummyRunner()
        channel_manager = DummyChannelManager()
        executor = CronExecutor(runner=runner, channel_manager=channel_manager)

        await executor.execute(make_agent_job("new_per_run"))
        await executor.execute(make_agent_job("new_per_run"))

        assert len(runner.requests) == 2
        first_session = runner.requests[0]["session_id"]
        second_session = runner.requests[1]["session_id"]
        assert first_session != "target-session"
        assert second_session != "target-session"
        assert first_session != second_session
        assert first_session.startswith("cron:job-1:")
        assert second_session.startswith("cron:job-1:")

        assert len(channel_manager.events) == 2
        for event_call in channel_manager.events:
            assert event_call["session_id"] == "target-session"
            assert event_call["meta"]["dispatch_session_id"] == "target-session"
            assert event_call["meta"]["session_mode"] == "new_per_run"
            assert event_call["meta"]["execution_session_id"].startswith("cron:job-1:")

    asyncio.run(_run())


def test_cron_executor_text_task_still_uses_dispatch_session() -> None:
    async def _run() -> None:
        runner = DummyRunner()
        channel_manager = DummyChannelManager()
        executor = CronExecutor(runner=runner, channel_manager=channel_manager)
        job = make_agent_job("new_per_run").model_copy(
            update={
                "task_type": "text",
                "text": "hello text",
                "request": None,
            }
        )

        await executor.execute(job)

        assert runner.requests == []
        assert len(channel_manager.texts) == 1
        text_call = channel_manager.texts[0]
        assert text_call["session_id"] == "target-session"
        assert text_call["meta"]["dispatch_session_id"] == "target-session"
        assert text_call["meta"]["session_mode"] == "new_per_run"
        assert text_call["meta"]["execution_session_id"].startswith("cron:job-1:")

    asyncio.run(_run())
