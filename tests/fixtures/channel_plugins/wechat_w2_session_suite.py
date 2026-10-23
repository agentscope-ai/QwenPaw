"""W2 sessions through actual G3 Loader/Service/worker/local HTTP.

The existing sample is a genuine generic management producer, not a WeChat
Driver substitute. Its offline HTTP endpoint is the external platform boundary.
"""

import asyncio
import hashlib
from importlib import import_module
import os
from types import SimpleNamespace

from fastapi import HTTPException
import psutil
import pytest
import pytest_asyncio

from management_process_suite import (
    GUARD,
    KEY,
    active_management,
    eventually,
    local_management_http,
    management_runtime,
)
from wechat_w2_config_support import write_profiles
from wechat_w2_scope_suite import request


@pytest.fixture(autouse=True)
def narrow_legacy_test_guard(monkeypatch):
    # The old fixture's qrcode*/wechat* prefix predates these host modules.
    # Keep its real Driver/SDK isolation guard; exempt only these exact hosts.
    original = GUARD.blocks
    allowed = {
        "qwenpaw.app.channels.qrcode_sessions",
        "qwenpaw.app.channels.wechat_auth_custody",
        "qwenpaw.app.channels.qrcode_auth_handler",
    }
    monkeypatch.setattr(
        GUARD,
        "blocks",
        lambda name: name not in allowed and original(name),
    )


@pytest_asyncio.fixture
async def qr(management_runtime, local_management_http, tmp_path, monkeypatch):
    rt = await management_runtime()
    config, paths = write_profiles(
        tmp_path,
        monkeypatch,
        KEY,
        {
            "enabled": False,
            "host": local_management_http.host,
            "port": local_management_http.port,
        },
    )
    api = import_module("qwenpaw.app.channels.qrcode_sessions")
    sessions = api.ChannelQRCodeSessions(rt.loader, rt.service)
    scope = api.resolve_channel_management_scope(request(header="A"), KEY)
    try:
        yield SimpleNamespace(
            rt=rt,
            http=local_management_http,
            sessions=sessions,
            scope=scope,
            api=api,
            paths=paths,
            config=config,
        )
    finally:
        await sessions.aclose()


def qr_leases(qr):
    return tuple(
        l for l in qr.rt.owners.leases() if l.key.kind == "qrcode_session"
    )


@pytest.mark.asyncio
async def test_real_fetch_poll_opaque_token_and_independent_management_generations(
    qr,
):
    fetched = await qr.sessions.fetch(qr.scope, {})
    assert fetched.scan_url == "https://fixture.invalid/scan"
    assert fetched.poll_token != "fixture-continuation"
    assert len(fetched.poll_token) == 43
    assert fetched.poll_token not in repr(vars(qr.sessions))
    assert hashlib.sha256(fetched.poll_token.encode()).hexdigest() in repr(
        vars(qr.sessions)
    )
    (session_lease,) = qr_leases(qr)
    assert session_lease.key.scope_id == str(qr.paths["A"].resolve())
    assert session_lease.key.name == KEY
    assert qr.rt.owners.resource(session_lease) is not None
    assert not active_management(qr.rt)
    first = qr.http.requests[0]
    assert first["pid"] != os.getpid() and not psutil.pid_exists(first["pid"])
    assert first["workspace_id"] == "A"
    result = await qr.sessions.poll(qr.scope, fetched.poll_token)
    assert result.status == "confirmed"
    assert result.credentials == {"api_token": "fixture-result-secret"}
    second = qr.http.requests[1]
    assert second["request_id"] != first["request_id"]
    assert second["continuation"] == "fixture-continuation"
    assert qr_leases(qr) == (session_lease,)
    assert not active_management(qr.rt)
    again = await qr.sessions.poll(qr.scope, fetched.poll_token)
    assert (
        again.credentials == result.credentials and len(qr.http.requests) == 2
    )


@pytest.mark.asyncio
async def test_physical_slot_overlap_and_cross_workspace_token_are_rejected(
    qr,
    tmp_path,
    monkeypatch,
):
    write_profiles(
        tmp_path,
        monkeypatch,
        KEY,
        {
            "enabled": False,
            "host": qr.http.host,
            "port": qr.http.port,
        },
        shared_path=True,
    )
    scope = qr.api.resolve_channel_management_scope(request(header="A"), KEY)
    alias_scope = qr.api.resolve_channel_management_scope(
        request(header="B"), KEY
    )
    assert scope.workspace_dir == alias_scope.workspace_dir
    fetched = await qr.sessions.fetch(scope, {})
    before = qr.rt.owners.leases()
    with pytest.raises((HTTPException, RuntimeError)):
        await qr.sessions.fetch(alias_scope, {})
    with pytest.raises(HTTPException) as forbidden:
        await qr.sessions.poll(alias_scope, fetched.poll_token)
    assert forbidden.value.status_code == 403
    assert qr.rt.owners.leases() == before
    assert len(qr.http.requests) == 1


@pytest.mark.asyncio
async def test_cancelled_poll_waiter_does_not_cancel_other_waiter(qr):
    fetched = await qr.sessions.fetch(qr.scope, {})
    qr.http.reply_gate.clear()
    first = asyncio.create_task(qr.sessions.poll(qr.scope, fetched.poll_token))
    second = asyncio.create_task(
        qr.sessions.poll(qr.scope, fetched.poll_token)
    )
    try:
        await eventually(lambda: len(qr.http.requests) == 2)
        (lease,) = active_management(qr.rt)
        pid = qr.rt.owners.resource(lease).health_snapshot()["pid"]
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert not second.done() and psutil.pid_exists(pid)
        qr.http.reply_gate.set()
        result = await second
        assert result.status == "confirmed" and len(qr.http.requests) == 2
        assert not psutil.pid_exists(pid)
    finally:
        qr.http.reply_gate.set()
        for task in (first, second):
            if not task.done():
                task.cancel()
        await asyncio.gather(first, second, return_exceptions=True)


@pytest.mark.asyncio
async def test_last_waiter_cancel_stops_exact_operation_but_allows_explicit_poll(
    qr,
):
    fetched = await qr.sessions.fetch(qr.scope, {})
    qr.http.reply_gate.clear()
    task = asyncio.create_task(qr.sessions.poll(qr.scope, fetched.poll_token))
    try:
        await eventually(lambda: len(qr.http.requests) == 2)
        (lease,) = active_management(qr.rt)
        pid = qr.rt.owners.resource(lease).health_snapshot()["pid"]
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not active_management(qr.rt) and not psutil.pid_exists(pid)
        assert qr_leases(qr)
        qr.http.reply_gate.set()
        result = await qr.sessions.poll(qr.scope, fetched.poll_token)
        assert result.status == "confirmed"
        assert len(qr.http.requests) == 3
        assert (
            qr.http.requests[2]["continuation"]
            == qr.http.requests[1]["continuation"]
        )
    finally:
        qr.http.reply_gate.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_delete_revokes_secret_and_reaps_poll_worker_without_credentials(
    qr,
):
    fetched = await qr.sessions.fetch(qr.scope, {})
    qr.http.reply_gate.clear()
    task = asyncio.create_task(qr.sessions.poll(qr.scope, fetched.poll_token))
    try:
        await eventually(lambda: len(qr.http.requests) == 2)
        (lease,) = active_management(qr.rt)
        pid = qr.rt.owners.resource(lease).health_snapshot()["pid"]
        await qr.sessions.cancel(qr.scope, fetched.poll_token)
        qr.http.reply_gate.set()
        result = await asyncio.gather(task, return_exceptions=True)
        assert not any(getattr(item, "credentials", {}) for item in result)
        assert not psutil.pid_exists(pid) and not qr_leases(qr)
        await qr.sessions.cancel(qr.scope, fetched.poll_token)
        with pytest.raises(HTTPException) as revoked:
            await qr.sessions.poll(qr.scope, fetched.poll_token)
        assert revoked.value.status_code == 400
    finally:
        qr.http.reply_gate.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_hard_ttl_discards_late_confirmed_and_clears_owner(
    qr, monkeypatch
):
    now = [qr.api.monotonic()]
    monkeypatch.setattr(qr.api, "monotonic", lambda: now[0])
    fetched = await qr.sessions.fetch(qr.scope, {})
    qr.http.reply_gate.clear()
    task = asyncio.create_task(qr.sessions.poll(qr.scope, fetched.poll_token))
    try:
        await eventually(lambda: len(qr.http.requests) == 2)
        now[0] += 301
        qr.http.reply_gate.set()
        result = await task
        assert result.status == "expired" and result.credentials == {}
        assert not qr_leases(qr) and not active_management(qr.rt)
    finally:
        qr.http.reply_gate.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_confirmed_authorize_save_consumes_only_successful_sync_commit(
    qr,
):
    from qwenpaw.config.config import load_agent_config, save_agent_config

    fetched = await qr.sessions.fetch(qr.scope, {})
    confirmed = await qr.sessions.poll(qr.scope, fetched.poll_token)
    values = {**qr.scope.config, **confirmed.credentials}
    with pytest.raises(ValueError, match="caller aborted"):
        async with qr.sessions.authorize_save(
            qr.scope, fetched.poll_token, values
        ):
            raise ValueError("caller aborted")
    scheduled = []
    asyncio.get_running_loop().call_soon(scheduled.append, "loop-turn")
    async with qr.sessions.authorize_save(
        qr.scope, fetched.poll_token, values
    ):
        assert scheduled == []  # Validation-to-save entry must not await.
        profile = load_agent_config("A")
        setattr(profile.channels, KEY, values)
        save_agent_config("A", profile)
    assert not qr_leases(qr)
    assert (
        getattr(load_agent_config("A").channels, KEY)["api_token"]
        == "fixture-result-secret"
    )
    with pytest.raises(HTTPException):
        async with qr.sessions.authorize_save(
            qr.scope, fetched.poll_token, values
        ):
            raise AssertionError("consumed auth token admitted twice")


@pytest.mark.asyncio
async def test_qr_owner_and_stop_adapter_exist_before_external_fetch_reply(qr):
    from qwenpaw.plugins.ownership import RuntimeSourceBusyError

    qr.http.reply_gate.clear()
    fetch = asyncio.create_task(qr.sessions.fetch(qr.scope, {}))
    try:
        await eventually(lambda: len(qr.http.requests) == 1)
        (lease,) = qr_leases(qr)
        assert qr.rt.owners.resource(lease) is not None
        snapshot = qr.rt.usage.snapshot()
        # Every RuntimeOwner appears as unknown metadata in the established
        # usage snapshot. That fallback is not a new dependency declaration.
        assert lease not in qr.rt.usage._bindings
        assert set(qr.rt.usage._bindings) == set(active_management(qr.rt))
        assert sum(use.origin == "declaration" for use in snapshot.uses) == (
            qr.rt.baseline_declaration_count + 1
        )
        with pytest.raises(RuntimeSourceBusyError):
            with qr.rt.owners.mutation(qr.rt.record.source_path):
                raise AssertionError("in-flight QR source mutation admitted")
        qr.http.reply_gate.set()
        await fetch
    finally:
        qr.http.reply_gate.set()
        if not fetch.done():
            fetch.cancel()
        await asyncio.gather(fetch, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["path", "profile-disabled", "config"])
async def test_authority_change_wins_over_late_confirmed_credentials(
    qr,
    tmp_path,
    change,
):
    from qwenpaw.config.config import (
        AgentProfileConfig,
        load_agent_config,
        save_agent_config,
    )
    from qwenpaw.config.utils import load_config, save_config

    fetched = await qr.sessions.fetch(qr.scope, {})
    qr.http.reply_gate.clear()
    poll = asyncio.create_task(qr.sessions.poll(qr.scope, fetched.poll_token))
    try:
        await eventually(lambda: len(qr.http.requests) == 2)
        if change == "config":
            profile = load_agent_config("A")
            value = dict(getattr(profile.channels, KEY))
            value["behavior"] = "authority-changed"
            setattr(profile.channels, KEY, value)
            save_agent_config("A", profile)
        else:
            config = load_config()
            moved = None
            if change == "path":
                moved = AgentProfileConfig.model_validate(
                    load_agent_config("A").model_dump()
                )
                config.agents.profiles["A"].workspace_dir = str(
                    tmp_path / "new-A"
                )
                moved.workspace_dir = str(tmp_path / "new-A")
            else:
                config.agents.profiles["A"].enabled = False
            save_config(config)
            if moved is not None:
                save_agent_config("A", moved)
        qr.http.reply_gate.set()
        outcome = (await asyncio.gather(poll, return_exceptions=True))[0]
        assert isinstance(outcome, HTTPException)
        assert outcome.status_code == 403  # Must not become expired/{}.
    finally:
        qr.http.reply_gate.set()
        if not poll.done():
            poll.cancel()
        await asyncio.gather(poll, return_exceptions=True)


@pytest.mark.asyncio
async def test_unknown_fetch_is_not_automatically_reissued(qr):
    from qwenpaw.app.channels.management import ManagementError

    qr.http.response = {"__exit_worker": True}
    with pytest.raises(ManagementError) as unknown:
        await qr.sessions.fetch(qr.scope, {})
    assert unknown.value.reason_code == "PLATFORM_RESULT_UNKNOWN"
    assert unknown.value.side_effect_possible
    assert len(qr.http.requests) == 1 and not active_management(qr.rt)


@pytest.mark.asyncio
async def test_revoke_workspace_and_channel_preserve_other_physical_slot(qr):
    a = await qr.sessions.fetch(qr.scope, {})
    scope_b = qr.api.resolve_channel_management_scope(request(header="B"), KEY)
    b = await qr.sessions.fetch(scope_b, {})
    assert len(qr_leases(qr)) == 2
    await qr.sessions.revoke_workspace("A")
    (remaining,) = qr_leases(qr)
    assert remaining.key.scope_id == str(qr.paths["B"].resolve())
    with pytest.raises(HTTPException):
        await qr.sessions.poll(qr.scope, a.poll_token)
    assert (
        await qr.sessions.poll(scope_b, b.poll_token)
    ).status == "confirmed"
    await qr.sessions.revoke_channel("B", KEY)
    assert not qr_leases(qr)
    with pytest.raises(HTTPException):
        await qr.sessions.poll(scope_b, b.poll_token)


@pytest.mark.asyncio
async def test_confirmed_cancel_drops_product_owned_operation_result_secret(
    qr,
):
    fetched = await qr.sessions.fetch(qr.scope, {})
    unique = "w2-unique-credential-must-leave-closed-session"
    qr.http.response = {
        "status": "confirmed",
        "credentials": {"api_token": unique},
    }
    delivered = await qr.sessions.poll(qr.scope, fetched.poll_token)
    assert delivered.credentials == {"api_token": unique}
    del delivered  # The oracle examines only production-owned references.
    digest = hashlib.sha256(fetched.poll_token.encode()).hexdigest()
    session = qr.sessions._sessions[digest]
    await qr.sessions.cancel(qr.scope, fetched.poll_token)
    assert session.credentials == {} and session.continuation == ""
    assert not qr_leases(qr) and not active_management(qr.rt)
    held = session.operation
    if held is not None and held.done() and not held.cancelled():
        assert unique not in repr(
            held.result()
        ), "closed production session still owns credential through done poll Task"


@pytest.mark.asyncio
async def test_loader_disable_stops_owned_poll_and_prevents_late_credentials(
    qr,
):
    fetched = await qr.sessions.fetch(qr.scope, {})
    qr.http.reply_gate.clear()
    poll = asyncio.create_task(qr.sessions.poll(qr.scope, fetched.poll_token))
    try:
        await eventually(lambda: len(qr.http.requests) == 2)
        (lease,) = active_management(qr.rt)
        pid = qr.rt.owners.resource(lease).health_snapshot()["pid"]
        report = await qr.rt.loader.lifecycle.set_enabled(
            qr.rt.record.manifest.id, False
        )
        assert report.quiescent and not report.needs_restart
        qr.http.reply_gate.set()
        outcomes = await asyncio.gather(poll, return_exceptions=True)
        assert not any(
            getattr(outcome, "credentials", {}) for outcome in outcomes
        )
        assert not qr_leases(qr) and not active_management(qr.rt)
        assert not psutil.pid_exists(pid)
        with pytest.raises(HTTPException):
            await qr.sessions.poll(qr.scope, fetched.poll_token)
    finally:
        qr.http.reply_gate.set()
        if not poll.done():
            poll.cancel()
        await asyncio.gather(poll, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "confirm_at,valid_at,expired_at", [(0, 59, 61), (250, 299, 301)]
)
async def test_terminal_cache_is_sixty_seconds_bounded_by_original_hard_ttl(
    qr,
    monkeypatch,
    confirm_at,
    valid_at,
    expired_at,
):
    initial = qr.api.monotonic()
    now = [initial]
    monkeypatch.setattr(qr.api, "monotonic", lambda: now[0])
    fetched = await qr.sessions.fetch(qr.scope, {})
    now[0] = initial + confirm_at
    confirmed = await qr.sessions.poll(qr.scope, fetched.poll_token)
    assert confirmed.status == "confirmed"
    now[0] = initial + valid_at
    cached = await qr.sessions.poll(qr.scope, fetched.poll_token)
    assert (
        cached.status == "confirmed"
        and cached.credentials == confirmed.credentials
    )
    assert len(qr.http.requests) == 2
    now[0] = initial + expired_at
    expired = await qr.sessions.poll(qr.scope, fetched.poll_token)
    assert expired.status == "expired" and expired.credentials == {}
    await qr.sessions.cancel(qr.scope, fetched.poll_token)
    assert not qr_leases(qr) and not active_management(qr.rt)
