"""QR state and immediate-response cancellation regressions on production code."""

import asyncio
from importlib import import_module

from fastapi import HTTPException, Request
import pytest
import pytest_asyncio

from management_process_suite import (
    KEY,
    management_runtime,
    local_management_http,
)
from wechat_w2_session_suite import qr, narrow_legacy_test_guard


async def drain_new_tasks(previous):
    """A regression must fail promptly and leave no watcher alive in pytest."""
    for _ in range(3):
        pending = {
            task for task in asyncio.all_tasks() - previous if not task.done()
        }
        pending.discard(asyncio.current_task())
        if not pending:
            return
        for task in pending:
            task.cancel()
        done, _ = await asyncio.wait(pending, timeout=0.3)
        for task in done:
            if not task.cancelled():
                task.exception()
    assert not {
        task
        for task in asyncio.all_tasks() - previous
        if task is not asyncio.current_task() and not task.done()
    }, "test cleanup could not stop a QR request watcher"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome,status",
    [("ACCOUNT_IN_USE", 409), ("PLUGIN_NOT_INSTALLED", 404), ("success", 200)],
)
async def test_immediate_qrcode_outcome_finishes_with_real_starlette_receive(
    outcome, status
):
    """Starlette's is_disconnected CancelScope may swallow watcher.cancel()."""
    routes = import_module("qwenpaw.app.routers.config")
    from qwenpaw.app.channels.management import ManagementError

    previous = set(asyncio.all_tasks())
    receive_entered = asyncio.Event()

    async def receive():
        receive_entered.set()
        await asyncio.Event().wait()

    request = Request(
        {"type": "http", "method": "GET", "path": "/qr", "headers": []},
        receive=receive,
    )

    async def operation():
        if outcome == "success":
            return {
                "qrcode_img": "fixture-image",
                "poll_token": "fixture-token",
            }
        raise ManagementError(outcome)

    task = asyncio.create_task(routes._qrcode_request(request, operation()))
    try:
        await asyncio.wait_for(receive_entered.wait(), timeout=0.5)
        done, _ = await asyncio.wait({task}, timeout=0.35)
        assert (
            task in done
        ), "immediate QR outcome hung while cleaning up Starlette disconnect watcher"
        if status == 200:
            assert task.result() == {
                "qrcode_img": "fixture-image",
                "poll_token": "fixture-token",
            }
        else:
            with pytest.raises(HTTPException) as denied:
                task.result()
            assert (denied.value.status_code, denied.value.detail) == (
                status,
                outcome,
            )
        assert not {
            pending
            for pending in asyncio.all_tasks() - previous
            if pending is not asyncio.current_task() and not pending.done()
        }, "completed QR request leaked a disconnect watcher"
    finally:
        await drain_new_tasks(previous)


@pytest.mark.asyncio
async def test_outer_qrcode_cancellation_propagates_after_operation_and_watcher_cleanup():
    routes = import_module("qwenpaw.app.routers.config")
    previous = set(asyncio.all_tasks())
    receive_entered, operation_entered, operation_stopped = (
        asyncio.Event() for _ in range(3)
    )

    async def receive():
        receive_entered.set()
        await asyncio.Event().wait()

    async def operation():
        operation_entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            operation_stopped.set()

    request = Request(
        {"type": "http", "method": "GET", "path": "/qr", "headers": []},
        receive=receive,
    )
    task = asyncio.create_task(routes._qrcode_request(request, operation()))
    try:
        await asyncio.wait_for(operation_entered.wait(), timeout=0.5)
        await asyncio.wait_for(receive_entered.wait(), timeout=0.5)
        task.cancel()
        done, _ = await asyncio.wait({task}, timeout=0.35)
        assert (
            task in done
        ), "outer cancellation hung in disconnect watcher cleanup"
        with pytest.raises(asyncio.CancelledError):
            task.result()
        assert operation_stopped.is_set()
        assert not {
            pending
            for pending in asyncio.all_tasks() - previous
            if pending is not asyncio.current_task() and not pending.done()
        }, "cancelled QR request leaked an operation or disconnect watcher"
    finally:
        await drain_new_tasks(previous)


@pytest_asyncio.fixture
async def schema_case(qr):
    """Keep real profiles, Workspace, Manager, Loader, registry and owners."""
    from fastapi import FastAPI
    from qwenpaw.app.multi_agent_manager import MultiAgentManager
    from qwenpaw.app.workspace import Workspace
    from qwenpaw.config.config import load_agent_config

    app = FastAPI()
    app.state.plugin_loader = qr.rt.loader
    app.state.channel_management = qr.rt.service
    app.state.channel_qrcode_sessions = qr.sessions
    manager = MultiAgentManager()
    workspace = Workspace("A", str(qr.paths["A"]))
    workspace._config = load_agent_config("A")
    manager.agents["A"] = workspace
    app.state.multi_agent_manager = manager
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/config/channels/schemas",
            "headers": [(b"x-agent-id", b"A")],
            "app": app,
        }
    )
    routes = import_module("qwenpaw.app.routers.config")

    async def read():
        return await routes.list_channel_schemas(request)

    return qr, workspace, read


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_schema_qrcode_ready_ignores_saved_enabled_and_reports_all_missing_official_plugins(
    schema_case, enabled
):
    fixture, workspace, read = schema_case
    getattr(workspace._config.channels, KEY)["enabled"] = enabled
    rows = await read()
    assert rows[KEY]["qrcode_available"] is True
    for key in ("feishu", "dingtalk", "qq", "wecom", "wechat"):
        assert rows[key]["availability"] == "missing_code"
        assert rows[key]["qrcode_available"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["running", "stopping", "failed-stop"])
async def test_schema_qrcode_stays_unavailable_until_exact_channel_lease_is_released(
    schema_case, state
):
    from qwenpaw.app.channels.management import ManagementError
    from qwenpaw.plugins.ownership import RuntimeKey, RuntimeStopReceipt

    fixture, _, read = schema_case
    owners = fixture.rt.owners
    gate, stopping = asyncio.Event(), asyncio.Event()
    release = False

    async def stop():
        stopping.set()
        if state == "stopping":
            await gate.wait()
        return RuntimeStopReceipt(
            release, "controlled stop evidence", exited=release
        )

    lease = owners.reserve(
        KEY,
        RuntimeKey("channel", KEY, str(fixture.paths["A"].resolve())),
        fixture.rt.record.source_path,
        instance_id="qr-state-channel",
    )
    owners.attach(lease, stop)
    task = None
    try:
        if state == "stopping":
            task = asyncio.create_task(owners.stop(lease))
            await asyncio.wait_for(stopping.wait(), timeout=0.5)
        elif state == "failed-stop":
            assert not (await owners.stop(lease)).stopped
        # No connected Channel object exists; custody is the admission gate.
        assert (await read())[KEY]["qrcode_available"] is False
        with pytest.raises(ManagementError) as denied:
            await fixture.sessions.fetch(fixture.scope, {})
        assert denied.value.reason_code == "ACCOUNT_IN_USE"
        release = True
        gate.set()
        if task is not None:
            assert (await task).stopped
        else:
            assert (await owners.stop(lease)).stopped
        assert (await read())[KEY]["qrcode_available"] is True
    finally:
        release = True
        gate.set()
        if task is not None:
            await task
        await owners.stop(lease)


@pytest.mark.asyncio
async def test_schema_qrcode_ignores_other_workspace_lease_and_current_qr_session(
    schema_case,
):
    from qwenpaw.app.channels.management import ManagementError
    from qwenpaw.plugins.ownership import RuntimeKey, RuntimeStopReceipt

    fixture, _, read = schema_case
    owners = fixture.rt.owners
    lease = owners.reserve(
        KEY,
        RuntimeKey("channel", KEY, str(fixture.paths["B"].resolve())),
        fixture.rt.record.source_path,
        instance_id="other-workspace",
    )
    try:
        assert (await read())[KEY]["qrcode_available"] is True
        fetched = await fixture.sessions.fetch(fixture.scope, {})
        assert fetched.poll_token
        assert (await read())[KEY]["qrcode_available"] is True
        # An existing QR session stays visible but still excludes a second fetch.
        with pytest.raises(ManagementError) as denied:
            await fixture.sessions.fetch(fixture.scope, {})
        assert denied.value.reason_code == "ACCOUNT_IN_USE"
    finally:
        owners.release(lease, RuntimeStopReceipt(True))


@pytest.mark.asyncio
async def test_schema_disabled_plugin_is_unavailable_and_original_fetch_gate_remains(
    schema_case,
):
    from qwenpaw.app.channels.management import ManagementError

    fixture, _, read = schema_case
    await fixture.rt.loader.lifecycle.set_enabled(KEY, False)
    assert (await read())[KEY]["qrcode_available"] is False
    with pytest.raises(ManagementError) as denied:
        await fixture.sessions.fetch(fixture.scope, {})
    # Disabling an active plugin unloads its registration. Passive discovery
    # then retains its disabled catalog row without probing or starting it.
    assert denied.value.reason_code == "PLUGIN_NOT_INSTALLED"
    await fixture.rt.loader.load_plugin(
        fixture.rt.record.manifest,
        fixture.rt.record.source_path,
        {"enabled": False},
        activate=False,
    )
    assert (await read())[KEY]["qrcode_available"] is False
    with pytest.raises(ManagementError) as denied:
        await fixture.sessions.fetch(fixture.scope, {})
    assert denied.value.reason_code == "PLUGIN_DISABLED"


def test_read_only_qrcode_availability_is_removed_from_channel_config():
    from qwenpaw.app.channels.catalog import clean_channel_config

    assert clean_channel_config(
        {"enabled": False, "qrcode_available": False, "app_id": "preserve-me"}
    ) == {"enabled": False, "app_id": "preserve-me"}
