# -*- coding: utf-8 -*-
"""Scheduled jobs survive replacement through delivery and history writes."""

# pylint: disable=protected-access,redefined-outer-name
# pylint: disable=too-many-locals,too-many-statements
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from apscheduler.events import EVENT_JOB_MAX_INSTANCES

from qwenpaw.app.crons.contracts import ServiceCronJob

from qwenpaw.app.crons.manager import CronManager
from qwenpaw.app.crons.models import CronJobSpec
from qwenpaw.app.crons.repo.json_repo import JsonJobRepository
from qwenpaw.app.multi_agent_manager import MultiAgentManager
from qwenpaw.app.workspace import Workspace
from qwenpaw.app.workspace.service_manager import (
    ServiceDescriptor,
    ServiceManager,
)


@pytest.fixture
def cron_workspace(tmp_path, monkeypatch):
    """Build real cron services with external model/channel seams replaced."""
    monkeypatch.setattr(
        "qwenpaw.app.crons.manager.get_heartbeat_config",
        lambda _agent: SimpleNamespace(enabled=False),
    )
    for name in (
        "read_session_messages",
        "create_trace",
        "append_trace_from_session_delta",
        "finalize_trace",
    ):
        monkeypatch.setattr(
            f"qwenpaw.app.crons.executor.{name}",
            AsyncMock(return_value=[]),
        )

    def make(name):
        workspace = Workspace(
            agent_id="agent-1",
            workspace_dir=str(tmp_path / name),
        )
        workspace._service_manager = ServiceManager(workspace)
        repo = JsonJobRepository(tmp_path / name / "jobs.json")
        channels = SimpleNamespace(send_event=AsyncMock())
        workspace._service_manager.register(
            ServiceDescriptor(
                name="cron_manager",
                stop_method="stop",
                reusable=False,
            ),
        )

        async def start():
            workspace._start_attempted = True
            cron = CronManager(
                repo=repo,
                workspace=workspace,
                channel_manager=channels,
                agent_id="agent-1",
                start_paused=workspace.cron_start_paused,
            )
            workspace._service_manager.services["cron_manager"] = cron
            await cron.start()
            workspace._started = True

        workspace.start = start
        return workspace, repo, channels

    return make


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked_stage", ["model", "delivery", "history"])
async def test_reload_preserves_scheduled_run_until_history_saved(
    cron_workspace,
    monkeypatch,
    blocked_stage,
):
    """Every phase must drain before the outgoing workspace is stopped."""
    old, repo, channels = cron_workspace("old")
    new, _, _ = cron_workspace("new")
    entered, release = asyncio.Event(), asyncio.Event()
    cancelled = asyncio.Event()

    async def block():
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    async def stream(_request):
        if blocked_stage == "model":
            await block()
        yield SimpleNamespace(object="message", status="completed")

    old.stream_query = stream
    if blocked_stage == "delivery":

        async def send_event(**_kwargs):
            await block()

        channels.send_event.side_effect = send_event
    append_history = repo.append_history

    async def save_history(*args, **kwargs):
        if blocked_stage == "history":
            await block()
        return await append_history(*args, **kwargs)

    monkeypatch.setattr(repo, "append_history", save_history)
    job = CronJobSpec(
        id="scheduled",
        name="scheduled",
        schedule={"cron": "0 0 1 1 *"},
        request={"input": "test"},
        dispatch={
            "mode": "stream",
            "target": {"user_id": "u", "session_id": "s"},
        },
        save_result_to_inbox=False,
    )
    await repo.upsert_job(job)
    manager = MultiAgentManager()
    manager.agents[old.agent_id] = old
    manager._create_workspace = MagicMock(return_value=new)
    manager._setup_workspace_plugins = AsyncMock()
    monkeypatch.setattr(
        "qwenpaw.app.multi_agent_manager.load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(
                profiles={
                    "agent-1": SimpleNamespace(
                        workspace_dir=str(new.workspace_dir),
                    ),
                },
            ),
        ),
    )
    try:
        await old.start()
        old.cron_manager._scheduler.add_job(
            old.cron_manager._scheduled_callback,
            "date",
            args=[job.id],
            id="run-now",
        )
        await asyncio.wait_for(entered.wait(), 3)
        assert await manager.reload_agent("agent-1")
        await asyncio.sleep(0)
        assert old._started, f"workspace stopped during {blocked_stage}"
        assert not cancelled.is_set()
        assert await repo.get_history(job.id) == []
        cleanup = list(manager._cleanup_tasks)
        assert cleanup
        release.set()
        await asyncio.wait_for(asyncio.gather(*cleanup), 3)
        history = await repo.get_history(job.id)
        assert len(history) == 1
        assert history[0].status == "success"
        assert history[0].trigger == "scheduled"
        assert not old._started
        channels.send_event.assert_awaited_once()
    finally:
        release.set()
        await manager.cancel_all_cleanup_tasks()
        await old.stop()
        await new.stop()
        await asyncio.sleep(0)


@pytest.mark.asyncio
@pytest.mark.parametrize("startup_result", ["success", "failure", "cancel"])
async def test_candidate_cannot_run_crons_before_commit(
    cron_workspace,
    monkeypatch,
    startup_result,
):
    """Only the active scheduler may consume an occurrence during startup."""
    old, old_repo, _ = cron_workspace("old")
    new, new_repo, _ = cron_workspace("new")
    old_ran, new_ran = asyncio.Event(), asyncio.Event()
    startup_entered, release_startup = asyncio.Event(), asyncio.Event()

    async def old_stream(_request):
        old_ran.set()
        yield None

    async def new_stream(_request):
        new_ran.set()
        yield None

    old.stream_query = old_stream
    new.stream_query = new_stream
    job = CronJobSpec(
        id="once",
        name="once",
        schedule={
            "type": "once",
            "run_at": datetime.now(timezone.utc) + timedelta(seconds=0.5),
        },
        request={"input": "test"},
        dispatch={
            "silent": True,
            "target": {"user_id": "u", "session_id": "s"},
        },
        save_result_to_inbox=False,
    )
    await old_repo.upsert_job(job)
    await new_repo.upsert_job(job)
    manager = MultiAgentManager()
    manager.agents["agent-1"] = old
    manager._create_workspace = MagicMock(return_value=new)

    async def plugin_startup(*_args):
        startup_entered.set()
        await release_startup.wait()
        if startup_result == "failure":
            raise RuntimeError("plugin startup failed")

    manager._setup_workspace_plugins = plugin_startup
    monkeypatch.setattr(
        "qwenpaw.app.multi_agent_manager.load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(
                profiles={
                    "agent-1": SimpleNamespace(
                        workspace_dir=str(new.workspace_dir),
                    ),
                },
            ),
        ),
    )
    reload_task = None
    try:
        await old.start()
        reload_task = asyncio.create_task(manager.reload_agent("agent-1"))
        await asyncio.wait_for(startup_entered.wait(), 3)
        await asyncio.wait_for(old_ran.wait(), 3)
        # Both instances know the same due job, but only the active instance
        # may execute it while candidate plugin startup is blocked.
        await asyncio.sleep(0.05)
        assert not new_ran.is_set()
        if startup_result == "cancel":
            reload_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await reload_task
        else:
            release_startup.set()
            assert await reload_task is (startup_result == "success")
        await asyncio.sleep(0.05)
        assert (
            not new_ran.is_set()
        ), "candidate replayed an already consumed one-shot job"
        if startup_result != "success":
            assert manager.agents["agent-1"] is old
            old_ran.clear()
            old.cron_manager._scheduler.add_job(
                old.cron_manager._scheduled_callback,
                "date",
                args=[job.id],
                id="after-failure",
            )
            await asyncio.wait_for(old_ran.wait(), 3)
    finally:
        release_startup.set()
        if reload_task is not None and not reload_task.done():
            reload_task.cancel()
            await asyncio.gather(reload_task, return_exceptions=True)
        await manager.cancel_all_cleanup_tasks()
        await old.stop()
        await new.stop()
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_consecutive_reloads_wait_only_for_each_outgoing_workspace(
    cron_workspace,
    monkeypatch,
):
    """Retiring each generation depends only on its own executions."""
    first, first_repo, _ = cron_workspace("first")
    second, second_repo, _ = cron_workspace("second")
    third, _, _ = cron_workspace("third")
    entered = [asyncio.Event(), asyncio.Event()]
    release = [asyncio.Event(), asyncio.Event()]

    def producer(index):
        async def stream(_request):
            entered[index].set()
            await release[index].wait()
            yield None

        return stream

    first.stream_query = producer(0)
    second.stream_query = producer(1)
    job = CronJobSpec(
        id="running",
        name="running",
        schedule={"cron": "0 0 1 1 *"},
        request={"input": "test"},
        dispatch={
            "silent": True,
            "target": {"user_id": "u", "session_id": "s"},
        },
        runtime={"max_concurrency": 2},
        save_result_to_inbox=False,
    )
    await first_repo.upsert_job(job)
    await second_repo.upsert_job(job)
    manager = MultiAgentManager()
    manager.agents["agent-1"] = first
    manager._create_workspace = MagicMock(side_effect=[second, third])
    manager._setup_workspace_plugins = AsyncMock()
    monkeypatch.setattr(
        "qwenpaw.app.multi_agent_manager.load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(
                profiles={
                    "agent-1": SimpleNamespace(
                        workspace_dir=str(first.workspace_dir),
                    ),
                },
            ),
        ),
    )
    try:
        await first.start()
        for index, workspace in enumerate((first, second)):
            # This test intentionally allows two runs to check owner isolation.
            workspace.cron_manager._scheduler.add_job(
                workspace.cron_manager._scheduled_callback,
                "date",
                args=[job.id],
                id="run-now",
                max_instances=2,
            )
            await asyncio.wait_for(entered[index].wait(), 3)
            assert await manager.reload_agent("agent-1")
        assert first._started and second._started and third._started
        cleanups = list(manager._cleanup_tasks)
        assert len(cleanups) == 2
        release[0].set()
        done, pending = await asyncio.wait(
            cleanups,
            timeout=3,
            return_when=asyncio.FIRST_COMPLETED,
        )
        assert len(done) == 1
        assert len(pending) == 1
        assert not first._started
        assert second._started
        release[1].set()
        await asyncio.wait_for(asyncio.gather(*pending), 3)
        assert not second._started
        assert third._started
        history = await first_repo.get_history(job.id)
        assert len(history) == 2
        assert all(record.status == "success" for record in history)
    finally:
        for event in release:
            event.set()
        await manager.cancel_all_cleanup_tasks()
        for workspace in (first, second, third):
            await workspace.stop()
        await asyncio.sleep(0)


@pytest.fixture
def reload_pair(cron_workspace, monkeypatch):
    """Configure a real replacement lifecycle and one scheduled job."""
    old, repo, _ = cron_workspace("old")
    new, _, _ = cron_workspace("new")
    manager = MultiAgentManager()
    manager.agents["agent-1"] = old
    manager._create_workspace = MagicMock(return_value=new)
    manager._setup_workspace_plugins = AsyncMock()
    monkeypatch.setattr(
        "qwenpaw.app.multi_agent_manager.load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(
                profiles={
                    "agent-1": SimpleNamespace(
                        workspace_dir=str(new.workspace_dir),
                    ),
                },
            ),
        ),
    )
    job = CronJobSpec(
        id="running",
        name="running",
        schedule={"cron": "0 0 1 1 *"},
        request={"input": "test"},
        dispatch={
            "silent": True,
            "target": {"user_id": "u", "session_id": "s"},
        },
        runtime={"max_concurrency": 1},
        save_result_to_inbox=False,
    )
    return manager, old, new, repo, job


@pytest.mark.asyncio
@pytest.mark.parametrize("stop_method", ["stop_all", "stop_agent"])
async def test_shutdown_immediately_after_reload_drains_cancelled_history(
    reload_pair,
    stop_method,
):
    """Shutdown owns retiring workspaces even before cleanup first runs."""
    manager, old, new, repo, job = reload_pair
    entered, cancelled = asyncio.Event(), asyncio.Event()
    other = SimpleNamespace(stop=AsyncMock())
    manager.agents["other-agent"] = other

    async def stream(_request):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        yield None

    old.stream_query = stream
    await repo.upsert_job(job)
    try:
        await old.start()
        old.cron_manager._scheduler.add_job(
            old.cron_manager._scheduled_callback,
            "date",
            args=[job.id],
        )
        await asyncio.wait_for(entered.wait(), 3)
        assert await manager.reload_agent("agent-1")
        # Deliberately no yield: delayed cleanup may not have started yet.
        if stop_method == "stop_all":
            await manager.stop_all()
            assert not manager.list_loaded_agents()
            other.stop.assert_awaited_once()
        else:
            assert await manager.stop_agent("agent-1")
            assert manager.list_loaded_agents() == ["other-agent"]
            other.stop.assert_not_awaited()
        assert not old._started and not new._started
        assert cancelled.is_set()
        history = await repo.get_history(job.id)
        assert len(history) == 1
        assert history[0].status == "cancelled"
    finally:
        await manager.stop_all()


@pytest.mark.asyncio
async def test_manual_request_crossing_handoff_runs_on_new_workspace(
    reload_pair,
    monkeypatch,
):
    """A pending manual request must follow the committed successor."""
    manager, old, new, repo, job = reload_pair
    reading, read_release = asyncio.Event(), asyncio.Event()
    running, run_release = asyncio.Event(), asyncio.Event()
    old.stream_query = MagicMock(
        side_effect=AssertionError("retired workspace used"),
    )

    async def stream(_request):
        running.set()
        await run_release.wait()
        yield None

    new.stream_query = stream
    get_job = repo.get_job

    async def blocked_read(job_id):
        reading.set()
        await read_release.wait()
        return await get_job(job_id)

    await repo.upsert_job(job)
    request = None
    try:
        await old.start()
        monkeypatch.setattr(repo, "get_job", blocked_read)
        request = asyncio.create_task(old.cron_manager.run_job(job.id))
        await asyncio.wait_for(reading.wait(), 3)
        assert await manager.reload_agent("agent-1")
        assert not old._started
        read_release.set()
        await asyncio.wait_for(request, 3)
        await asyncio.wait_for(running.wait(), 3)
        active = list(new.cron_manager.snapshot_active_tasks().values())
        assert len(active) == 1
        run_release.set()
        await asyncio.wait_for(asyncio.gather(*active), 3)
        history = await repo.get_history(job.id)
        assert len(history) == 1
        assert history[0].status == "success"
        assert history[0].trigger == "manual"
        old.stream_query.assert_not_called()
    finally:
        read_release.set()
        run_release.set()
        if request is not None:
            await asyncio.gather(request, return_exceptions=True)
        await manager.stop_all()


@pytest.mark.asyncio
async def test_manual_runs_across_reload_share_job_concurrency_limit(
    reload_pair,
):
    """Manual runs remain protected and cannot exceed per-job concurrency."""
    manager, old, new, repo, job = reload_pair
    old_entered, old_release = asyncio.Event(), asyncio.Event()
    new_entered, new_release = asyncio.Event(), asyncio.Event()

    async def old_stream(_request):
        old_entered.set()
        await old_release.wait()
        yield None

    async def new_stream(_request):
        new_entered.set()
        await new_release.wait()
        yield None

    old.stream_query = old_stream
    new.stream_query = new_stream
    await repo.upsert_job(job)
    try:
        await old.start()
        await old.cron_manager.run_job(job.id)
        await asyncio.wait_for(old_entered.wait(), 3)
        assert await manager.reload_agent("agent-1")
        assert old._started
        await new.cron_manager.run_job(job.id)
        await asyncio.sleep(0.02)
        assert (
            not new_entered.is_set()
        ), "max_concurrency=1 overlapped generations"
        cleanup = list(manager._cleanup_tasks)
        active = list(new.cron_manager.snapshot_active_tasks().values())
        assert len(active) == 1
        old_release.set()
        await asyncio.wait_for(new_entered.wait(), 3)
        await asyncio.wait_for(asyncio.gather(*cleanup), 3)
        assert not old._started and new._started
        new_release.set()
        await asyncio.wait_for(asyncio.gather(*active), 3)
        history = await repo.get_history(job.id)
        assert len(history) == 2
        assert all(record.status == "success" for record in history)
    finally:
        old_release.set()
        new_release.set()
        await manager.stop_all()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["heartbeat", "service", "scheduled"])
async def test_scheduler_limits_survive_repeated_handoffs(
    cron_workspace,
    monkeypatch,
    kind,
):
    """Share job occupancy, but keep each scheduler's cancellation local."""
    workspaces = [cron_workspace(str(index))[0] for index in range(3)]
    entered = [asyncio.Event() for _ in workspaces]
    releases = [asyncio.Event() for _ in workspaces]
    cancelled = [asyncio.Event() for _ in workspaces]
    active = 0
    peak = 0

    async def blocked(index):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        entered[index].set()
        try:
            await releases[index].wait()
        except asyncio.CancelledError:
            cancelled[index].set()
            raise
        finally:
            active -= 1

    async def heartbeat(**kwargs):
        await blocked(workspaces.index(kwargs["workspace"]))

    monkeypatch.setattr(
        "qwenpaw.app.crons.manager.run_heartbeat_once",
        heartbeat,
    )
    job = CronJobSpec(
        id="shared",
        name="shared",
        schedule={"cron": "0 0 1 1 *"},
        request={"input": "test"},
        dispatch={
            "silent": True,
            "target": {"user_id": "u", "session_id": "s"},
        },
        save_result_to_inbox=False,
    )

    async def start(index):
        workspace = workspaces[index]
        workspace.cron_start_paused = index > 0
        await workspace.start()
        cron = workspace.cron_manager

        async def service():
            await blocked(index)

        async def stream(_request):
            await blocked(index)
            yield None

        workspace.stream_query = stream
        if kind == "heartbeat":
            callback, args = cron._heartbeat_callback, []
        elif kind == "service":
            declaration = ServiceCronJob("shared", "0 0 * * *", service)
            callback, args = cron._run_service_job, ["test", declaration]
        else:
            await cron._repo.upsert_job(job)
            callback, args = cron._scheduled_callback, [job.id]
        cron._scheduler.add_job(
            callback,
            "interval",
            seconds=0.02,
            id=job.id,
            args=args,
        )
        return cron

    try:
        old = await start(0)
        await asyncio.wait_for(entered[0].wait(), 3)
        previous = old
        for index in (1, 2):
            current = await start(index)
            skipped = asyncio.Event()
            current._scheduler.add_listener(
                lambda _event, done=skipped: done.set(),
                EVENT_JOB_MAX_INSTANCES,
            )
            current.handoff_from(previous)
            await asyncio.wait_for(skipped.wait(), 3)
            assert peak == 1, "same job ran concurrently across generations"
            assert not entered[index].is_set()
            previous = current
        unrelated = asyncio.Event()

        async def unrelated_callback():
            unrelated.set()

        current._scheduler.add_job(
            unrelated_callback,
            "date",
            id="unrelated",
        )
        await asyncio.wait_for(unrelated.wait(), 3)
        assert active == 1
        releases[0].set()
        await asyncio.wait_for(entered[2].wait(), 3)
        assert not entered[1].is_set()
        assert peak == 1
        await old.stop()
        await workspaces[1].cron_manager.stop()
        await asyncio.sleep(0)
        assert active == 1
        assert not cancelled[2].is_set()
        releases[2].set()
        current._scheduler.pause()
        await asyncio.wait_for(
            asyncio.gather(*current.snapshot_active_tasks().values()),
            3,
        )
        assert active == 0
    finally:
        for release in releases:
            release.set()
        for workspace in workspaces:
            await workspace.stop()
