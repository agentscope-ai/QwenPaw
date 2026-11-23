# -*- coding: utf-8 -*-
"""Native scheduler, isolated workspace storage, notifications and cancellation."""

import asyncio
from contextvars import ContextVar
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
import threading

from qwenpaw.app.crons.manager import CronManager
from qwenpaw.app.crons.repo.json_repo import JsonJobRepository
from qwenpaw.app.inbox_store import list_events
from qwenpaw.checkpoints.models import CheckpointError
from qwenpaw.checkpoints.restore import WorkspaceMutationGuard
from qwenpaw.checkpoints.runtime import RUNTIME
from qwenpaw.plugins.compliance import check_plugin
from qwenpaw.plugins.testing import PluginTestHost
from .sdk_author_fixture import make_plugin
from qwenpaw.plugins.workflows import (
    WorkflowSpec,
    WorkflowSchedule,
    WorkflowResult,
)
from qwenpaw.plugins.errors import ResourceError, SDKError

SOURCE = """
import asyncio
from qwenpaw.plugins.apps import PawApp
from qwenpaw.plugins.workflows import WorkflowSpec, WorkflowSchedule, WorkflowResult, WorkflowNotification
class Plugin:
    def register(self, ctx):
        async def work(call, parameters):
            key = call.workspace_id + '.json'
            state = {'number': ctx.storage.read_json(key, {}).get('number', 0) + 1,
                'state': 'running', 'workspace': call.workspace_id,
                'user': call.identity.user_id, 'session': call.session_id,
                'scheduled': call.scheduled}
            ctx.storage.write_json(key, state)
            try:
                await asyncio.sleep(parameters['delay'])
                text = f"{call.workspace_id}: report {state['number']}"
                return WorkflowResult(parameters['outcome'] != 'failure', text,
                    WorkflowNotification('SDK 定时报告', text))
            finally:
                state['state'] = 'cancelled' if call.cancelled else 'finished'
                ctx.storage.write_json(key, state)
        ctx.register_workflow(WorkflowSpec('report', work,
            WorkflowSchedule(ctx.config.get('cron', '* * * * *')),
            parameters={'delay': ctx.config.get('delay', 0), 'outcome': ctx.config.get('outcome', 'success')},
            timeout=ctx.config.get('timeout', 30)))
        app = PawApp(app_id='workflow-contract')
        @app.route('/status')
        async def status(call, request):
            return ctx.storage.read_json(call.workspace_id + '.json', {})
        ctx.register_app(app)
plugin = Plugin()
"""


@pytest.fixture
def workflow_plugin(tmp_path):
    return make_plugin(
        tmp_path,
        SOURCE,
        ["apps", "workflows", "storage", "config"],
        plugin_id="workflow-contract",
        sdk_version="1.2",
    )


PLUGIN = "workflow-contract"
JOB = "_service:sdk_" + PLUGIN + ":report"


async def cron(host, workspace_id):
    ws = await host._workspace(workspace_id)
    manager = CronManager(
        repo=JsonJobRepository(ws.workspace_dir / "jobs.json"),
        workspace=ws,
        channel_manager=None,
        agent_id=workspace_id,
    )
    ws._service_manager.services["cron_manager"] = manager
    await manager.start()
    return manager


def soon(manager):
    manager._scheduler.modify_job(
        JOB,
        next_run_time=datetime.now(timezone.utc) + timedelta(milliseconds=30),
    )


async def state(host, workspace="one"):
    response = await host.request(
        "GET",
        "/api/" + PLUGIN + "/status",
        workspace_id=workspace,
        user_id="alice",
    )
    assert response.status == 200, response.text
    return response.json()


async def until_state(host, expected, workspace="one"):
    async with asyncio.timeout(5):
        while (value := await state(host, workspace)).get("state") != expected:
            await asyncio.sleep(0.01)
        return value


async def test_native_workflow_schedule_scope_result_and_reload(
    tmp_path,
    workflow_plugin,
    caplog,
):
    assert check_plugin(workflow_plugin).ok
    async with PluginTestHost(tmp_path / "host") as host:
        managers = [await cron(host, name) for name in ("one", "two")]
        try:
            assert (await host.install(workflow_plugin)).ok
            for manager in managers:
                assert (
                    len(
                        [
                            j
                            for j in manager._scheduler.get_jobs()
                            if j.id == JOB
                        ],
                    )
                    == 1
                )
                soon(manager)
            for workspace in ("one", "two"):
                value = await until_state(host, "finished", workspace)
                assert value == {
                    "number": 1,
                    "state": "finished",
                    "workspace": workspace,
                    "user": "",
                    "session": "",
                    "scheduled": True,
                }
            async with asyncio.timeout(5):
                while len(events := await list_events(source_type="cron")) < 2:
                    await asyncio.sleep(0.01)
            assert {e["agent_id"] for e in events} == {"one", "two"}
            assert all(
                e["status"] == "success"
                and e["source_id"] == PLUGIN + ":report"
                for e in events
            )
            assert (
                await host.update_config(PLUGIN, {"outcome": "failure"})
            ).ok
            for manager in managers:
                assert (
                    len(
                        [
                            j
                            for j in manager._scheduler.get_jobs()
                            if j.id == JOB
                        ],
                    )
                    == 1
                )
            soon(managers[0])
            async with asyncio.timeout(5):
                while not (
                    errors := await list_events(status="error", agent_id="one")
                ):
                    await asyncio.sleep(0.01)
            assert errors[0]["event_type"] == "plugin_workflow"
            async with asyncio.timeout(5):
                while (
                    "Failed to execute sdk_workflow-contract cron job report"
                    not in caplog.text
                ):
                    await asyncio.sleep(0.01)
            assert (await state(host, "two"))["number"] == 1
            assert (await host.set_enabled(PLUGIN, False)).ok
            assert all(m._scheduler.get_job(JOB) is None for m in managers)
            assert (await host.set_enabled(PLUGIN, True)).ok
            assert all(m._scheduler.get_job(JOB) is not None for m in managers)
            result = await host.uninstall(PLUGIN)
            assert result.clean and result.quiescent
            assert all(m._scheduler.get_job(JOB) is None for m in managers)
        finally:
            for manager in managers:
                await manager.stop()


async def test_workflow_nonoverlap_cancel_timeout_and_unregister(
    tmp_path,
    workflow_plugin,
):
    async with PluginTestHost(tmp_path / "host") as host:
        manager = await cron(host, "one")
        try:
            assert (
                await host.install(
                    workflow_plugin,
                    config={"delay": 10, "timeout": 0.25},
                )
            ).ok
            soon(manager)
            await until_state(host, "running")
            soon(manager)
            value = await until_state(host, "cancelled")
            assert value["number"] == 1
            assert await list_events() == []
            assert (await host.update_config(PLUGIN, {"delay": 10})).ok
            soon(manager)
            await until_state(host, "running")
            result = await host.uninstall(PLUGIN, interrupt_tasks=True)
            assert result.clean and result.quiescent
            assert manager._scheduler.get_job(JOB) is None
            assert not any(
                not t.done() and PLUGIN + ":workflow" in t.get_name()
                for t in asyncio.all_tasks()
            )
        finally:
            await manager.stop()


async def test_workflow_retains_thread_and_clears_ambient_request(
    sdk_component,
    monkeypatch,
):
    from qwenpaw.plugins import custody

    monkeypatch.setattr(custody, "THREAD_STOP_SECONDS", 0.03)
    request_user = ContextVar("workflow_test_user", default="no-user")
    started, release = threading.Event(), threading.Event()
    calls, registrations = [], []
    stopping = None

    async def work(call, parameters):
        calls.append((request_user.get(), call.identity))

        def blocking():
            started.set()
            release.wait()

        await call.resources.run_sync(blocking)
        return WorkflowResult()

    def declare(ctx):
        registrations.append(
            ctx.register_workflow(
                WorkflowSpec(
                    "report",
                    work,
                    WorkflowSchedule("0 0 * * *", workspace_ids=("one",)),
                    timeout=0.03,
                ),
            ),
        )

    async with sdk_component(declare) as (host, ctx):
        managers = [await cron(host, name) for name in ("one", "two")]
        try:
            for ws in host._workspaces.values():
                await host._loader.registry.projector.project_workspace(ws)
            job_id = "_service:sdk_resource-contract:report"
            assert managers[1]._scheduler.get_job(job_id) is None
            token = request_user.set("installer-user")
            try:
                managers[0]._scheduler.modify_job(
                    job_id,
                    next_run_time=datetime.now(timezone.utc),
                )
                async with asyncio.timeout(3):
                    while not started.is_set():
                        await asyncio.sleep(0.01)
            finally:
                request_user.reset(token)
            assert calls[0][0] == "no-user" and calls[0][1].user_id == ""
            await asyncio.sleep(0.15)
            workspace = host._workspaces["one"]
            guard = WorkspaceMutationGuard(workspace, timeout=0.03)
            with pytest.raises(CheckpointError, match="did not become idle"):
                await guard.quiesce()
            assert await workspace.task_tracker.has_active_tasks()
            active = await workspace.task_tracker.snapshot_active_tasks()
            stopping = asyncio.create_task(
                workspace.task_tracker.request_stop(next(iter(active))),
            )
            await asyncio.sleep(0)
            with pytest.raises(CheckpointError, match="did not become idle"):
                await guard.quiesce()
            assert not stopping.done()
            managers[0]._scheduler.modify_job(
                job_id,
                next_run_time=datetime.now(timezone.utc),
            )
            await asyncio.sleep(0.15)
            assert len(calls) == 1, "The previous worker thread is still alive"
            with pytest.raises(ResourceError, match="did not stop"):
                await registrations[0].close()
            assert not registrations[0].closed
            assert managers[0]._scheduler.get_job(job_id) is None
        finally:
            release.set()
            await registrations[0].close()
            if stopping is not None:
                assert await stopping
            callbacks = await guard.quiesce()
            guard.resume(callbacks)
            assert await workspace.task_tracker.snapshot_active_tasks() == {}
            for manager in managers:
                await manager.stop()


async def test_workflow_rejected_by_shared_tracker_does_not_start(
    sdk_component,
):
    calls = []

    async def work(call, parameters):
        calls.append(call.workspace_id)
        return WorkflowResult()

    def declare(ctx):
        ctx.register_workflow(
            WorkflowSpec("report", work, WorkflowSchedule("0 0 * * *")),
        )

    async with sdk_component(declare) as (host, ctx):
        manager = await cron(host, "one")
        workspace = host._workspaces["one"]
        tracker = workspace.task_tracker
        owner = replace(ctx.resources.owner, workspace_id=workspace.agent_id)
        key = f"workflow:{owner}:resource-contract:report"
        release = asyncio.Event()
        old = tracker.start_background_task(
            key,
            lambda: asyncio.create_task(release.wait()),
        )
        try:
            await host._loader.registry.projector.project_workspace(workspace)
            job = manager._scheduler.get_job(
                "_service:sdk_resource-contract:report",
            )
            _, declaration = job.args
            with pytest.raises(ValueError, match="already tracked"):
                await declaration.callback()
            assert await tracker.snapshot_active_tasks() == {key: old}
            release.set()
            await old
            await declaration.callback()
            assert calls == ["one"]
        finally:
            release.set()
            await old
            await manager.stop()


@pytest.mark.parametrize("initialization_failed", [False, True])
async def test_workflow_does_not_require_checkpoint_initialization(
    sdk_component,
    monkeypatch,
    initialization_failed,
):
    calls = []

    async def work(call, parameters):
        calls.append(call.workspace_id)
        return WorkflowResult(text="completed without checkpoints")

    async with sdk_component() as (host, ctx):
        workspace = await host._workspace("one")
        initialize = Mock(side_effect=FileNotFoundError("git"))
        monkeypatch.setattr(RUNTIME, "_initialize_storage", initialize)
        if initialization_failed:
            with pytest.raises(FileNotFoundError, match="git"):
                await RUNTIME.get_for_workspace_async(workspace)
        ctx.register_workflow(
            WorkflowSpec("report", work, WorkflowSchedule("0 0 * * *")),
        )
        result = await host.run_workflow(
            "resource-contract:report",
            workspace_id="one",
        )
        assert result == WorkflowResult(text="completed without checkpoints")
        assert calls == ["one"]
        assert initialize.call_count == int(initialization_failed)


async def test_restore_waits_for_workflow_and_blocks_new_admission(
    sdk_component,
):
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def work(call, parameters):
        calls.append(call.workspace_id)
        entered.set()
        await release.wait()
        return WorkflowResult()

    async with sdk_component() as (host, ctx):
        manager = await cron(host, "one")
        ctx.register_workflow(
            WorkflowSpec("report", work, WorkflowSchedule("0 0 * * *")),
        )
        workspace = host._workspaces["one"]
        engine = None
        running = quiescing = None
        try:
            running = asyncio.create_task(
                host.run_workflow(
                    "resource-contract:report",
                    workspace_id="one",
                ),
            )
            await asyncio.wait_for(entered.wait(), 2)
            # Checkpoints may first initialize after workflow admission.
            engine = await RUNTIME.get_for_workspace_async(workspace)
            guard = WorkspaceMutationGuard(
                workspace,
                timeout=2,
                waiting_tasks=engine._query_waiters,
            )
            quiescing = asyncio.create_task(guard.quiesce())
            await asyncio.sleep(0.05)
            assert not quiescing.done()
            release.set()
            await running
            guard.resume(await quiescing)
            assert calls == ["one"]

            engine.query_gate.clear()
            running = asyncio.create_task(
                host.run_workflow(
                    "resource-contract:report",
                    workspace_id="one",
                ),
            )
            async with asyncio.timeout(2):
                while not engine._query_waiters:
                    await asyncio.sleep(0)
            callbacks = await guard.quiesce()
            assert calls == ["one"]
            assert not running.done()
            guard.resume(callbacks)
            engine.query_gate.set()
            await running
            assert calls == ["one", "one"]
        finally:
            release.set()
            if engine is not None:
                engine.query_gate.set()
            await asyncio.gather(
                *(task for task in (running, quiescing) if task is not None),
                return_exceptions=True,
            )
            await manager.stop()


async def test_workflow_invalid_declarations_leave_no_intents(sdk_component):
    async def work(call, values):
        return WorkflowResult()

    async with sdk_component() as (host, ctx):
        for schedule in (
            WorkflowSchedule("not cron"),
            WorkflowSchedule("* * * * *", timezone="Missing/Zone"),
            WorkflowSchedule("* * * * *", workspace_ids="one"),
        ):
            with pytest.raises((SDKError, ValueError, KeyError)):
                ctx.register_workflow(WorkflowSpec("bad", work, schedule))
        assert not host._loader.registry.projector._intents


async def test_public_workflow_helper_uses_registered_bridge(
    tmp_path,
    workflow_plugin,
):
    async with PluginTestHost(tmp_path / "host") as host:
        assert (
            await host.install(workflow_plugin, config={"cron": "0 0 1 1 *"})
        ).ok
        result = await host.run_workflow(
            PLUGIN + ":report",
            workspace_id="one",
            parameters={"delay": 0, "outcome": "success"},
        )
        assert result.success and result.text == "one: report 1"
        assert result.notification.title == "SDK 定时报告"
        assert (await state(host))["scheduled"] is False
        result = await host.run_workflow(
            PLUGIN + ":report",
            workspace_id="two",
            parameters={"delay": 0, "outcome": "failure"},
            scheduled=True,
        )
        assert not result.success and result.text == "two: report 1"
        assert (await state(host, "two"))["scheduled"] is True
        with pytest.raises(SDKError, match="not registered"):
            await host.run_workflow("another:report", workspace_id="one")
        running = asyncio.create_task(
            host.run_workflow(
                PLUGIN + ":report",
                workspace_id="one",
                parameters={"delay": 30, "outcome": "success"},
            ),
        )
        await until_state(host, "running")
        with pytest.raises(SDKError, match="already running"):
            await host.run_workflow(PLUGIN + ":report", workspace_id="one")
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
        assert (await state(host))["state"] == "cancelled"
        assert len(await list_events()) == 2
