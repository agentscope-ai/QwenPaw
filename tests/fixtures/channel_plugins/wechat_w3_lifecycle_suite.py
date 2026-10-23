"""W3 lifecycle integration with actual managers, sessions and HTTP workers.

Only persistence scheduling is gated to observe admission while the real
transition is suspended. No Workspace/Service/owner replacement is installed.
"""

import asyncio
from importlib import import_module

import pytest

from management_process_suite import (
    KEY,
    management_runtime,
    local_management_http,
    eventually,
)
from wechat_w2_session_suite import qr, qr_leases, narrow_legacy_test_guard
from wechat_w2_scope_suite import request
from wechat_w3_router_suite import api_http

__all__ = ["api_http"]


def scope_b(fixture):
    return fixture.qr.api.resolve_channel_management_scope(
        request(header="B"), KEY
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_caller", [False, True])
async def test_unloaded_workspace_stop_revokes_a_and_holds_admission_during_await(
    api_http, monkeypatch, cancel_caller
):
    fixture = api_http
    await fixture.qr.sessions.fetch(fixture.qr.scope, {})
    b = await fixture.qr.sessions.fetch(scope_b(fixture), {})
    entered, release = asyncio.Event(), asyncio.Event()
    original = fixture.manager._stop_agent
    calls = []

    async def gate(agent_id):
        calls.append(agent_id)
        entered.set()
        await release.wait()
        return await original(agent_id)

    monkeypatch.setattr(fixture.manager, "_stop_agent", gate)
    queued = None
    operation_lock = asyncio.Lock()
    if cancel_caller:
        await operation_lock.acquire()
        fixture.manager._operation_locks["A"] = operation_lock
    stopping = asyncio.create_task(fixture.manager.stop_agent("A"))
    if cancel_caller:
        queued = asyncio.create_task(fixture.manager.stop_agent("A"))
        async with asyncio.timeout(1):
            while len(fixture.manager._operations) != 2:
                await asyncio.sleep(0)
        operation_lock.release()
    try:
        await asyncio.wait_for(entered.wait(), 3)
        assert not fixture.manager.agents
        assert len(qr_leases(fixture.qr)) == 1
        busy = await fixture.client.get(f"/config/channels/{KEY}/qrcode")
        assert (
            busy.status_code == 409
            and busy.json()["detail"] == "MANAGEMENT_BUSY"
        )
        assert (
            await fixture.qr.sessions.poll(scope_b(fixture), b.poll_token)
        ).status == "confirmed"
        if cancel_caller:
            stopping.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(stopping, 1)
            busy = await fixture.client.get(f"/config/channels/{KEY}/qrcode")
            assert busy.status_code == 409
            assert busy.json()["detail"] == "MANAGEMENT_BUSY"
            assert queued is not None and not queued.done()
            stopping = queued
        release.set()
        assert await stopping is False
        assert calls == ["A"]
        reopened = await fixture.client.get(f"/config/channels/{KEY}/qrcode")
        assert reopened.status_code == 200, reopened.text
    finally:
        release.set()
        await asyncio.gather(stopping, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["disable", "delete"])
@pytest.mark.parametrize("persistence", ["success", "failure"])
async def test_unloaded_agent_transition_keeps_guard_until_actual_persistence(
    api_http, monkeypatch, operation, persistence
):
    from qwenpaw.config.utils import load_config

    fixture = api_http
    agents = import_module("qwenpaw.app.routers.agents")
    fixture.app.include_router(agents.router)
    await fixture.qr.sessions.fetch(fixture.qr.scope, {})
    b = await fixture.qr.sessions.fetch(scope_b(fixture), {})
    entered, release = asyncio.Event(), asyncio.Event()
    original = agents.run_sync_io

    async def persist_gate(func, *args, **kwargs):
        if func is agents.mutate_config:
            entered.set()
            await release.wait()
            if persistence == "failure":
                raise OSError("isolated persistence failure")
        return await original(func, *args, **kwargs)

    monkeypatch.setattr(agents, "run_sync_io", persist_gate)
    operation_task = asyncio.create_task(
        fixture.client.delete("/agents/A")
        if operation == "delete"
        else fixture.client.patch("/agents/A/toggle", json={"enabled": False})
    )
    try:
        await entered.wait()
        assert not fixture.manager.agents and len(qr_leases(fixture.qr)) == 1
        assert load_config().agents.profiles["A"].enabled
        busy = await fixture.client.get(f"/config/channels/{KEY}/qrcode")
        assert (
            busy.status_code == 409
            and busy.json()["detail"] == "MANAGEMENT_BUSY"
        )
        assert (
            await fixture.qr.sessions.poll(scope_b(fixture), b.poll_token)
        ).status == "confirmed"
        release.set()
        if persistence == "failure":
            with pytest.raises(OSError, match="isolated persistence failure"):
                await operation_task
            assert load_config().agents.profiles["A"].enabled
            reopened = await fixture.client.get(
                f"/config/channels/{KEY}/qrcode"
            )
            assert reopened.status_code == 200, reopened.text
        else:
            response = await operation_task
            assert response.status_code == 200, response.text
            unavailable = await fixture.client.get(
                f"/config/channels/{KEY}/qrcode"
            )
            assert unavailable.status_code == (
                404 if operation == "delete" else 403
            )
        if persistence == "success":
            assert all(
                lease.key.scope_id != str(fixture.qr.paths["A"].resolve())
                for lease in qr_leases(fixture.qr)
            )
    finally:
        release.set()
        await asyncio.gather(operation_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_manager_stop_all_closes_sessions_before_unloaded_workspaces(
    api_http,
):
    fixture = api_http
    await fixture.qr.sessions.fetch(fixture.qr.scope, {})
    await fixture.qr.sessions.fetch(scope_b(fixture), {})
    assert not fixture.manager.agents
    await fixture.manager.stop_all()
    assert not qr_leases(fixture.qr)
    response = await fixture.client.get(f"/config/channels/{KEY}/qrcode")
    assert (
        response.status_code == 503
        and response.json()["detail"] == "MANAGEMENT_CLOSED"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", [None, "sessions", "management", "cancel-then-error"]
)
async def test_actual_app_shutdown_orders_real_services_and_exposes_cleanup_failure(
    api_http, monkeypatch, failure
):
    from qwenpaw.portability.import_jobs import PortabilityImportJobManager

    fixture = api_http
    app_module = import_module("qwenpaw.app._app")
    await fixture.qr.sessions.fetch(fixture.qr.scope, {})
    imports = PortabilityImportJobManager()
    events = []

    def observe(obj, method, name, error=None):
        original = getattr(obj, method)

        async def call(*args, **kwargs):
            nonlocal error
            events.append(name)
            result = await original(*args, **kwargs)
            if error is not None:
                raised, error = error, None
                raise raised
            return result

        monkeypatch.setattr(obj, method, call)

    observe(
        fixture.qr.sessions,
        "aclose",
        "sessions",
        (
            asyncio.CancelledError()
            if failure == "cancel-then-error"
            else (
                RuntimeError("sessions cleanup failed")
                if failure == "sessions"
                else None
            )
        ),
    )
    observe(
        fixture.qr.rt.service,
        "aclose",
        "management",
        (
            RuntimeError("management cleanup failed")
            if failure in {"management", "cancel-then-error"}
            else None
        ),
    )
    observe(imports, "shutdown", "imports")
    observe(fixture.qr.rt.loader.lifecycle, "unload_all", "plugins")
    observe(fixture.manager, "stop_all", "workspaces")
    if failure:
        with pytest.raises(
            RuntimeError,
            match=(
                "management cleanup failed"
                if failure in {"management", "cancel-then-error"}
                else "sessions cleanup failed"
            ),
        ):
            await app_module._stop_workspaces_after_dependents_impl(
                fixture.app, imports
            )
        assert events == ["sessions", "management"]
    else:
        await app_module._stop_workspaces_after_dependents_impl(
            fixture.app, imports
        )
        assert events[:5] == [
            "sessions",
            "management",
            "imports",
            "plugins",
            "workspaces",
        ]
    assert not qr_leases(fixture.qr)
