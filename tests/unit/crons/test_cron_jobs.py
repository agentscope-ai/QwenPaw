# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from copaw.app.crons.executor import CronExecutor
from copaw.app.crons.models import CronJobSpec
from copaw.app.crons.repo.json_repo import JsonJobRepository


def _build_agent_payload(
    *,
    request_user_id: str | None = "system",
    request_session_id: str | None = "request-session",
    target_user_id: str = "target-user",
    target_session_id: str = "target-session",
) -> dict:
    return {
        "id": "job-1",
        "name": "repro",
        "enabled": True,
        "schedule": {
            "type": "cron",
            "cron": "0 9 * * *",
            "timezone": "UTC",
        },
        "task_type": "agent",
        "request": {
            "input": [
                {
                    "role": "user",
                    "type": "message",
                    "content": [{"type": "text", "text": "hello"}],
                },
            ],
            "user_id": request_user_id,
            "session_id": request_session_id,
        },
        "dispatch": {
            "type": "channel",
            "channel": "console",
            "target": {
                "user_id": target_user_id,
                "session_id": target_session_id,
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
    }


def test_agent_job_preserves_explicit_request_context() -> None:
    job = CronJobSpec.model_validate(_build_agent_payload())

    assert job.request is not None
    assert job.request.user_id == "system"
    assert job.request.session_id == "request-session"
    assert job.dispatch.target.user_id == "target-user"
    assert job.dispatch.target.session_id == "target-session"
    assert job.build_agent_request()["user_id"] == "system"
    assert job.build_agent_request()["session_id"] == "request-session"


async def test_json_repo_persists_explicit_request_context(
    tmp_path: Path,
) -> None:
    repo = JsonJobRepository(tmp_path / "jobs.json")

    await repo.upsert_job(CronJobSpec.model_validate(_build_agent_payload()))

    data = json.loads((tmp_path / "jobs.json").read_text(encoding="utf-8"))
    request = data["jobs"][0]["request"]
    assert request["user_id"] == "system"
    assert request["session_id"] == "request-session"


def test_build_agent_request_falls_back_to_dispatch_target() -> None:
    job = CronJobSpec.model_validate(
        _build_agent_payload(
            request_user_id=None,
            request_session_id=None,
        ),
    )

    request = job.build_agent_request()
    assert request["user_id"] == "target-user"
    assert request["session_id"] == "target-session"


class _FakeRunner:
    def __init__(self) -> None:
        self.requests: list[dict] = []

    async def stream_query(self, request: dict):
        self.requests.append(request)
        yield {"type": "done"}


class _FakeChannelManager:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def send_event(
        self,
        *,
        channel: str,
        user_id: str,
        session_id: str,
        event,
        meta=None,
    ) -> None:
        self.events.append(
            {
                "channel": channel,
                "user_id": user_id,
                "session_id": session_id,
                "event": event,
                "meta": meta,
            },
        )


async def test_executor_uses_request_context_and_dispatch_target() -> None:
    runner = _FakeRunner()
    channel_manager = _FakeChannelManager()
    executor = CronExecutor(runner=runner, channel_manager=channel_manager)
    job = CronJobSpec.model_validate(_build_agent_payload())

    await executor.execute(job)

    assert runner.requests == [
        {
            "input": [
                {
                    "role": "user",
                    "type": "message",
                    "content": [{"type": "text", "text": "hello"}],
                },
            ],
            "user_id": "system",
            "session_id": "request-session",
        },
    ]
    assert channel_manager.events == [
        {
            "channel": "console",
            "user_id": "target-user",
            "session_id": "target-session",
            "event": {"type": "done"},
            "meta": {},
        },
    ]
