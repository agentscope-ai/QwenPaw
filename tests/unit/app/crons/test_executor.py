# -*- coding: utf-8 -*-
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from qwenpaw.app.crons.executor import CronExecutor
from qwenpaw.app.crons.models import DispatchSpec, DispatchTarget
from qwenpaw.schemas import Event, RunStatus
from tests.unit.app.conftest import make_cron_job_spec


class _Workspace:
    chat_manager = None

    def __init__(self, events=None) -> None:
        self.events_consumed = 0
        self.events = events if events is not None else ("first", "second")

    async def stream_query(self, _request):
        for event in self.events:
            self.events_consumed += 1
            yield event


@pytest.mark.asyncio
async def test_runtime_identity_comes_from_validated_authorization(monkeypatch):
    from uuid import uuid4
    from qwenpaw.runtime_status.scope import execution_user_id

    observed = []
    class Workspace(_Workspace):
        async def stream_query(self, request):
            observed.append(request)
            if False:
                yield None

    user = str(uuid4())
    _patch_trace_storage(monkeypatch)
    job = make_cron_job_spec(job_id="identity-job")
    await CronExecutor(workspace=Workspace(), channel_manager=AsyncMock()).execute(
        job, authorization={"authorized_by_user_id": user},
    )
    assert execution_user_id(observed[0]["request_context"]) == user


def _patch_trace_storage(monkeypatch):
    monkeypatch.setattr(
        "qwenpaw.app.crons.executor.read_session_messages",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "qwenpaw.app.crons.executor.create_trace",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "qwenpaw.app.crons.executor.append_trace_from_session_delta",
        AsyncMock(),
    )
    finalize_trace = AsyncMock()
    monkeypatch.setattr(
        "qwenpaw.app.crons.executor.finalize_trace",
        finalize_trace,
    )
    return finalize_trace


@pytest.mark.asyncio
async def test_silent_agent_job_runs_without_channel_delivery(monkeypatch):
    workspace = _Workspace()
    channel_manager = AsyncMock()
    job = make_cron_job_spec(job_id="silent-job")
    job.dispatch = DispatchSpec(
        target=DispatchTarget(user_id="u1", session_id="console:u1"),
        silent=True,
    )

    finalize_trace = _patch_trace_storage(monkeypatch)

    result = await CronExecutor(
        workspace=workspace,
        channel_manager=channel_manager,
    ).execute(job)

    assert workspace.events_consumed == 2
    channel_manager.send_event.assert_not_awaited()
    assert result["delivery_status"] == "suppressed"
    finalize_trace.assert_awaited_once_with(result["run_id"], status="success")


@pytest.mark.asyncio
async def test_agent_job_still_delivers_by_default(monkeypatch):
    workspace = _Workspace()
    channel_manager = AsyncMock()
    job = make_cron_job_spec(job_id="normal-job")

    _patch_trace_storage(monkeypatch)

    result = await CronExecutor(
        workspace=workspace,
        channel_manager=channel_manager,
    ).execute(job)

    assert workspace.events_consumed == 2
    assert channel_manager.send_event.await_count == 2
    assert result["delivery_status"] == "success"


@pytest.mark.asyncio
async def test_agent_job_never_sets_tool_guard_off(monkeypatch):
    workspace = _Workspace()
    channel_manager = AsyncMock()
    job = make_cron_job_spec(job_id="governed-job")
    job.runtime.tool_safety = False
    captured = {}

    async def stream_query(request):
        captured.update(request["request_context"])
        if False:
            yield None

    workspace.stream_query = stream_query
    _patch_trace_storage(monkeypatch)

    await CronExecutor(
        workspace=workspace,
        channel_manager=channel_manager,
    ).execute(
        job,
        authorization={
            "schedule_id": "governed-job",
            "config_version": 1,
            "authorization_digest": "a" * 64,
            "grants": [{"capability": "tool:Read"}],
        },
    )

    assert captured["approval_level"] == "auto"
    assert captured["actor_type"] == "automation"
    assert captured["automation_authorization"]["schedule_id"] == "governed-job"


@pytest.mark.asyncio
async def test_final_mode_delivers_only_last_completed_message(monkeypatch):
    first = Event(
        object="message",
        status=RunStatus.Completed,
        data={"text": "first"},
    )
    progress = Event(object="message", status=RunStatus.InProgress)
    final = Event(
        object="message",
        status=RunStatus.Completed,
        data={"text": "final"},
    )
    workspace = _Workspace([first, progress, final])
    channel_manager = AsyncMock()
    job = make_cron_job_spec(job_id="final-job")
    job.dispatch = DispatchSpec(
        target=DispatchTarget(user_id="u1", session_id="console:u1"),
        mode="final",
    )

    _patch_trace_storage(monkeypatch)

    result = await CronExecutor(
        workspace=workspace,
        channel_manager=channel_manager,
    ).execute(job)

    assert workspace.events_consumed == 3
    channel_manager.send_event.assert_awaited_once()
    assert channel_manager.send_event.await_args.kwargs["event"] is final
    assert result["delivery_status"] == "success"


@pytest.mark.asyncio
async def test_final_mode_reports_delivery_failure(monkeypatch):
    final = Event(object="message", status=RunStatus.Completed)
    workspace = _Workspace([final])
    channel_manager = AsyncMock()
    channel_manager.send_event.side_effect = RuntimeError("channel down")
    job = make_cron_job_spec(job_id="final-failure-job")
    job.dispatch = DispatchSpec(
        target=DispatchTarget(user_id="u1", session_id="console:u1"),
        mode="final",
    )

    _patch_trace_storage(monkeypatch)

    result = await CronExecutor(
        workspace=workspace,
        channel_manager=channel_manager,
    ).execute(job)

    channel_manager.send_event.assert_awaited_once()
    assert result["delivery_status"] == "failed"
    assert "channel down" in result["delivery_error"]


@pytest.mark.asyncio
async def test_final_mode_no_completed_message_returns_no_content(monkeypatch):
    progress = Event(object="message", status=RunStatus.InProgress)
    workspace = _Workspace([progress])
    channel_manager = AsyncMock()
    job = make_cron_job_spec(job_id="final-empty-job")
    job.dispatch = DispatchSpec(
        target=DispatchTarget(user_id="u1", session_id="console:u1"),
        mode="final",
    )

    _patch_trace_storage(monkeypatch)

    result = await CronExecutor(
        workspace=workspace,
        channel_manager=channel_manager,
    ).execute(job)

    assert workspace.events_consumed == 1
    channel_manager.send_event.assert_not_awaited()
    assert result["delivery_status"] == "no_content"
