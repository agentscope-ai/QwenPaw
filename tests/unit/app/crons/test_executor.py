# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.app.crons.executor import (
    CronExecutor,
    _cron_run_session_prefix,
)
from qwenpaw.app.crons.models import DispatchSpec, DispatchTarget
from qwenpaw.schemas import Event, RunStatus
from tests.unit.app.conftest import make_cron_job_spec


class _Workspace:
    chat_manager = None

    def __init__(self, events=None) -> None:
        self.events_consumed = 0
        self.events = events if events is not None else ("first", "second")
        self.requests = []

    async def stream_query(self, request):
        self.requests.append(request)
        for event in self.events:
            self.events_consumed += 1
            yield event


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


@pytest.mark.asyncio
async def test_non_shared_job_reuses_its_dedicated_session(
    monkeypatch,
):
    workspace = _Workspace()
    workspace.chat_manager = AsyncMock()
    workspace.chat_manager.get_or_create_chat.side_effect = [
        SimpleNamespace(id="chat-1"),
        SimpleNamespace(id="chat-2"),
    ]
    channel_manager = AsyncMock()
    job = make_cron_job_spec(
        job_id="imported/job id",
        session_id="../unsafe/" + ("x" * 200),
    )
    job.runtime.share_session = False

    _patch_trace_storage(monkeypatch)

    executor = CronExecutor(
        workspace=workspace,
        channel_manager=channel_manager,
    )
    first = await executor.execute(job)
    second = await executor.execute(job)

    first_session = workspace.requests[0]["session_id"]
    second_session = workspace.requests[1]["session_id"]
    assert first["run_id"] != second["run_id"]
    assert first_session == second_session
    assert first_session == first["session_id"]
    assert second_session == second["session_id"]
    assert first_session.startswith("cron:")
    assert ":job:" in first_session
    assert ":run:" not in first_session
    assert len(first_session) <= 115
    assert re.fullmatch(r"[A-Za-z0-9:._-]+", first_session)
    assert workspace.requests[0]["session_source"] == "cron"

    chat_calls = workspace.chat_manager.get_or_create_chat.await_args_list
    assert [call.kwargs["session_id"] for call in chat_calls] == [
        first_session,
        second_session,
    ]
    assert all(call.kwargs["source"] == "cron" for call in chat_calls)


@pytest.mark.asyncio
async def test_timeout_preserves_run_reference(monkeypatch):
    import asyncio

    from qwenpaw.app.crons.executor import CronExecutionTimeout

    class SlowWorkspace(_Workspace):
        async def stream_query(self, request):
            await asyncio.Event().wait()
            yield

    job = make_cron_job_spec(job_id="timeout-job")
    job.runtime.timeout_seconds = 0.01
    finalize = _patch_trace_storage(monkeypatch)
    executor = CronExecutor(
        workspace=SlowWorkspace(),
        channel_manager=AsyncMock(),
    )
    with pytest.raises(CronExecutionTimeout) as error:
        await executor.execute(job)
    assert error.value.run_id
    finalize.assert_awaited_once_with(
        error.value.run_id,
        status="timeout",
        error="timed out after 0.01s",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "selection",
    [None, {"provider_id": "p", "model": "chosen:v1"}],
)
async def test_execution_model_override_is_per_request(monkeypatch, selection):
    from unittest.mock import MagicMock
    from qwenpaw.providers import ProviderManager

    workspace = _Workspace()
    job = make_cron_job_spec(job_id="model-job")
    job.request = job.request.model_copy(
        update={"model_slot_override": selection},
    )
    provider = SimpleNamespace(
        all_models=lambda: [SimpleNamespace(id="chosen:v1")],
    )
    manager = MagicMock()
    manager.get_provider.return_value = provider
    monkeypatch.setattr(ProviderManager, "get_instance", lambda: manager)
    _patch_trace_storage(monkeypatch)
    await CronExecutor(
        workspace=workspace,
        channel_manager=AsyncMock(),
    ).execute(job)
    assert workspace.requests[0]["model_slot_override"] == selection
    manager.set_active_model.assert_not_called()
    if selection is None:
        manager.get_provider.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "selection,exists",
    [
        ({"provider_id": "p", "model": "gone"}, True),
        ({"provider_id": "p", "model": "gone"}, False),
        ("invalid", True),
    ],
)
async def test_invalid_execution_model_fails_without_running(
    monkeypatch,
    selection,
    exists,
):
    from unittest.mock import MagicMock
    from qwenpaw.providers import ProviderManager

    workspace = _Workspace()
    job = make_cron_job_spec(job_id="model-job")
    job.request = job.request.model_copy(
        update={"model_slot_override": selection},
    )
    manager = MagicMock()
    manager.get_provider.return_value = (
        SimpleNamespace(all_models=lambda: []) if exists else None
    )
    monkeypatch.setattr(ProviderManager, "get_instance", lambda: manager)
    finalize = _patch_trace_storage(monkeypatch)
    with pytest.raises(ValueError, match="[Mm]odel"):
        await CronExecutor(
            workspace=workspace,
            channel_manager=AsyncMock(),
        ).execute(job)
    assert not workspace.requests
    assert finalize.call_args.kwargs["status"] == "error"


@pytest.mark.asyncio
async def test_default_clears_nested_override_without_changing_job(
    monkeypatch,
):
    workspace = _Workspace()
    job = make_cron_job_spec(job_id="default-job")
    nested = {"model_slot_override": {"provider_id": "old", "model": "old"}}
    job.request = job.request.model_copy(
        update={
            "model_slot_override": None,
            "request_context": nested,
        },
    )
    _patch_trace_storage(monkeypatch)
    await CronExecutor(
        workspace=workspace,
        channel_manager=AsyncMock(),
    ).execute(job)
    assert (
        "model_slot_override" not in workspace.requests[0]["request_context"]
    )
    assert job.request.request_context == nested


@pytest.mark.asyncio
async def test_external_backend_does_not_silently_ignore_model(monkeypatch):
    from unittest.mock import MagicMock
    from qwenpaw.providers import ProviderManager

    workspace = _Workspace()
    workspace.config = SimpleNamespace(backend="external")
    job = make_cron_job_spec(job_id="external-job")
    job.request = job.request.model_copy(
        update={
            "model_slot_override": {"provider_id": "p", "model": "m"},
        },
    )
    manager = MagicMock()
    manager.get_provider.return_value = SimpleNamespace(
        all_models=lambda: [SimpleNamespace(id="m")],
    )
    monkeypatch.setattr(ProviderManager, "get_instance", lambda: manager)
    _patch_trace_storage(monkeypatch)
    with pytest.raises(ValueError, match="select Default"):
        await CronExecutor(
            workspace=workspace,
            channel_manager=AsyncMock(),
        ).execute(job)
    assert not workspace.requests


@pytest.mark.asyncio
async def test_per_run_session_job_gets_distinct_session_per_run(
    monkeypatch,
):
    workspace = _Workspace()
    workspace.chat_manager = AsyncMock()
    workspace.chat_manager.get_or_create_chat.side_effect = [
        SimpleNamespace(id="chat-1"),
        SimpleNamespace(id="chat-2"),
    ]
    workspace.chat_manager.list_chats = AsyncMock(return_value=[])
    channel_manager = AsyncMock()
    job = make_cron_job_spec(job_id="job-1")
    job.runtime.share_session = False
    job.runtime.per_run_session = True

    _patch_trace_storage(monkeypatch)

    executor = CronExecutor(
        workspace=workspace,
        channel_manager=channel_manager,
    )
    first = await executor.execute(job)
    second = await executor.execute(job)

    first_session = workspace.requests[0]["session_id"]
    second_session = workspace.requests[1]["session_id"]
    assert first_session != second_session
    assert first_session == first["session_id"]
    assert second_session == second["session_id"]
    expected_prefix = _cron_run_session_prefix(
        target_session_id="console:u1",
        job_id="job-1",
    )
    assert first_session.startswith(expected_prefix)
    assert second_session.startswith(expected_prefix)
    assert workspace.requests[0]["session_source"] == "cron"

    chat_calls = workspace.chat_manager.get_or_create_chat.await_args_list
    assert [call.kwargs["session_id"] for call in chat_calls] == [
        first_session,
        second_session,
    ]
    # Run chats carry a timestamp so operators can tell runs apart.
    assert all("·" in call.kwargs["name"] for call in chat_calls)


@pytest.mark.asyncio
async def test_per_run_session_trims_old_run_chats(monkeypatch, tmp_path):
    workspace = _Workspace()
    workspace.chat_manager = AsyncMock()
    workspace.chat_manager.get_or_create_chat.return_value = SimpleNamespace(
        id="chat-new",
    )
    workspace.chat_manager.delete_chats = AsyncMock(return_value=True)
    prefix = _cron_run_session_prefix(
        target_session_id="console:u1",
        job_id="job-1",
    )
    now = datetime.now(timezone.utc)

    def _run_chat(idx: int):
        return SimpleNamespace(
            id=f"chat-{idx}",
            session_id=f"{prefix}run-{idx}",
            user_id="u1",
            channel="console",
            created_at=now - timedelta(minutes=idx),
        )

    # Retention default is 50; pin it low so the trim is exercisable.
    monkeypatch.setattr(
        "qwenpaw.app.crons.executor._CRON_PER_RUN_CHAT_KEEP",
        3,
    )
    run_chats = [_run_chat(i) for i in range(5)]
    unrelated = SimpleNamespace(
        id="chat-other",
        session_id="console:u1",
        user_id="u1",
        channel="console",
        created_at=now,
    )
    workspace.chat_manager.list_chats = AsyncMock(
        return_value=run_chats + [unrelated],
    )
    removed_files: list[str] = []
    workspace.session = SimpleNamespace(
        delete_session_file=lambda session_id, user_id, channel: (
            removed_files.append(session_id) or True
        ),
    )
    channel_manager = AsyncMock()
    job = make_cron_job_spec(job_id="job-1")
    job.runtime.share_session = False
    job.runtime.per_run_session = True

    _patch_trace_storage(monkeypatch)

    executor = CronExecutor(
        workspace=workspace,
        channel_manager=channel_manager,
    )
    await executor.execute(job)

    workspace.chat_manager.delete_chats.assert_awaited_once()
    stale_ids = workspace.chat_manager.delete_chats.await_args.args[0]
    # Newest `keep=3` run chats survive; oldest 2 are removed.
    assert sorted(stale_ids) == ["chat-3", "chat-4"]
    assert sorted(removed_files) == [
        f"{prefix}run-3",
        f"{prefix}run-4",
    ]
    # Unrelated chats are never touched.
    assert "console:u1" not in removed_files


@pytest.mark.asyncio
async def test_legacy_job_sessions_are_not_trimmed(monkeypatch):
    workspace = _Workspace()
    workspace.chat_manager = AsyncMock()
    workspace.chat_manager.get_or_create_chat.return_value = SimpleNamespace(
        id="chat-1",
    )
    workspace.chat_manager.list_chats = AsyncMock(return_value=[])
    channel_manager = AsyncMock()
    job = make_cron_job_spec(job_id="job-1")
    job.runtime.share_session = False

    _patch_trace_storage(monkeypatch)

    executor = CronExecutor(
        workspace=workspace,
        channel_manager=channel_manager,
    )
    await executor.execute(job)

    # Legacy per-job chat flow must not invoke run-chat housekeeping.
    workspace.chat_manager.list_chats.assert_not_awaited()
    workspace.chat_manager.delete_chats.assert_not_awaited()
