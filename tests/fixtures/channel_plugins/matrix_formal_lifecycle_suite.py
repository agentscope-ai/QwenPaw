"""Matrix account isolation and real native-auth activation rollback."""
import json
from contextlib import asynccontextmanager

from aiohttp import web
import psutil
import pytest

from extension_process_suite import eventually, identity, runtime
from matrix_formal_agent_suite import assert_original_archive, formal_source
from matrix_formal_support import (
    BOT,
    ROOM,
    LocalMatrixAPI,
    matrix_host_guard,
    sync_payload,
    text_event,
)
from real_host_runtime import bind_real_runtime

__all__ = ["runtime", "matrix_host_guard"]


@asynccontextmanager
async def server(user, device):
    api = LocalMatrixAPI()
    api.user, api.device = user, device
    async def account_http(request):
        response = await api.handle(request)
        if "/joined_members" in request.path:
            # A second authenticated account must appear in its own HS room.
            body = json.loads(response.body)
            body["joined"][api.user] = body["joined"].pop(BOT)
            return web.json_response(body, status=response.status)
        return response

    app = web.Application()
    app.router.add_route("*", "/{path:.*}", account_http)
    runner = web.AppRunner(
        app, shutdown_timeout=0.1, handler_cancellation=True
    )
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    api.url = "http://127.0.0.1:" + str(
        site._server.sockets[0].getsockname()[1]
    )
    try:
        yield api
    finally:
        api.closed.set()
        await runner.cleanup()


async def create(runtime, api, **kwargs):
    return await runtime(
        "matrix",
        source_factory=formal_source,
        homeserver=api.url,
        user_id=api.user,
        access_token="token-" + api.device,
        streaming_enabled=False,
        **kwargs,
    )


async def ready(rt, api):
    rt.channel = await rt.manager.get_channel("matrix")
    rt.process = rt.channel.channel_process
    rt.record = rt.loader.get_loaded_plugin("matrix")
    await eventually(
        lambda: rt.process.health_snapshot()["platform_state"] == "connected"
    )
    count = len(api.calls("/sync"))
    api.sync.put_nowait((sync_payload("catchup-" + str(count)), 200))
    await eventually(lambda: len(api.calls("/sync")) > count)
    return rt.process.health_snapshot()["pid"]


async def exchange(rt, api, text):
    before, requests = len(api.sent), len(rt.ws.requests)
    api.sync.put_nowait(
        (sync_payload(text, [text_event(text, "$" + text)]), 200)
    )
    await eventually(lambda: len(api.sent) == before + 1)
    assert await rt.ws.task_tracker.wait_all_done(timeout=8)
    assert len(rt.ws.requests) == requests + 1
    assert api.sent[-1]["body"]["body"] == "actual agent answer"
    assert (
        api.sent[-1]["headers"]["Authorization"]
        == "Bearer token-" + api.device
    )
    return {
        p: p.read_bytes()
        for p in (rt.ws.workspace_dir / "sessions").rglob("*.json")
    }


@pytest.mark.asyncio
async def test_formal_distinct_accounts_stop_one_keeps_other_agent_and_state(
    runtime, monkeypatch
):
    async with server(BOT, "DEVICE-A") as a, server(
        "@bot-b:example.com", "DEVICE-B"
    ) as b:
        first = await create(runtime, a, workspace_name="matrix-A")
        first_host = await bind_real_runtime(first, monkeypatch)
        second = await create(
            runtime, b, existing_loader=first.loader, workspace_name="matrix-B"
        )
        second_host = await bind_real_runtime(second, monkeypatch)
        pids = [await ready(first, a), await ready(second, b)]
        assert len(set(pids)) == 2 and all(psutil.pid_exists(p) for p in pids)
        owners = first.loader.registry.runtime_owners
        leases = [
            r for r in owners.leases("matrix") if r.key.kind == "channel"
        ]
        assert len(leases) == 2
        assert {id(owners.resource(r)) for r in leases} == {
            id(first.channel),
            id(second.channel),
        }
        assert_original_archive(first)
        assert_original_archive(second)
        a_sessions = await exchange(first, a, "workspace-A")
        b_sessions = await exchange(second, b, "workspace-B")
        assert (
            a_sessions
            and b_sessions
            and set(a_sessions).isdisjoint(b_sessions)
        )
        assert all(
            b"workspace-A" in v and b"workspace-B" not in v
            for v in a_sessions.values()
        )
        assert all(
            b"workspace-B" in v and b"workspace-A" not in v
            for v in b_sessions.values()
        )
        assert len(first_host.builds) == len(second_host.builds) == 1
        old_identity = identity(first)
        receipt = await first.manager.stop_one("matrix")
        assert receipt.stopped and receipt.exited and not receipt.residual
        assert not psutil.pid_exists(pids[0]) and psutil.pid_exists(pids[1])
        await exchange(second, b, "B-after-A-stop")
        assert len(first_host.builds) == 1 and len(second_host.builds) == 2
        assert {p: p.read_bytes() for p in a_sessions} == a_sessions
        fresh = (
            await first.manager.start_one("matrix", first.ws.config)
        ).channel
        await ready(first, a)
        assert fresh._launch_spec.generation > old_identity["generation"]
        from qwenpaw.channel_protocol.errors import RpcError

        with pytest.raises(RpcError) as stale:
            await fresh.channel_process.call(
                "channel.response.open",
                {
                    **old_identity,
                    "to_handle": "matrix:" + ROOM,
                    "meta": {},
                },
            )
        assert stale.value.data["reason_code"] == "STALE_GENERATION"
        assert len(a.sent) == 1
        assert (await second.manager.stop_one("matrix")).stopped
        assert not psutil.pid_exists(pids[1])
        assert psutil.pid_exists(first.process.health_snapshot()["pid"])
        assert (await first.manager.stop_one("matrix")).stopped
        assert not owners.leases("matrix")


@pytest.mark.asyncio
async def test_enabled_candidate_auth_failure_restores_matrix_state_and_agent(
    runtime, monkeypatch, tmp_path
):
    async with server(BOT, "DEVICE-ROLLBACK") as api:
        rt = await create(runtime, api)
        host = await bind_real_runtime(rt, monkeypatch)
        old_pid = await ready(rt, api)
        sessions = await exchange(rt, api, "before-update")
        assert sessions
        original = assert_original_archive(rt)
        old_identity = identity(rt)
        old_config = dict(rt.channel._launch_spec.config)
        candidate = formal_source(tmp_path / "candidate", "matrix")
        manifest_path = candidate / "plugin.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["version"] = "99.0.0"
        manifest_path.write_text(json.dumps(manifest))
        # Only the external homeserver rejects candidate activation; real
        # Driver/nio/start/Loader rollback all execute unchanged.
        api.whoami.append(
            (
                {
                    "errcode": "M_UNKNOWN_TOKEN",
                    "error": "candidate token refused",
                },
                401,
            )
        )
        before_auth = len(api.calls("/whoami"))
        report = await rt.loader.lifecycle.reload(
            "matrix", new_source=candidate
        )
        assert not report.ok and report.errors
        assert len(api.calls("/whoami")) == before_auth + 2
        new_pid = await ready(rt, api)
        assert new_pid != old_pid and not psutil.pid_exists(old_pid)
        assert identity(rt)["generation"] > old_identity["generation"]
        assert (
            rt.channel.enabled
            and dict(rt.channel._launch_spec.config) == old_config
        )
        assert assert_original_archive(rt) == original
        assert {p: p.read_bytes() for p in sessions} == sessions
        await exchange(rt, api, "after-rollback")
        assert len(host.builds) == 2
        assert all(
            b"before-update" in p.read_bytes()
            and b"after-rollback" in p.read_bytes()
            for p in sessions
        )
        assert (await rt.manager.stop_one("matrix")).stopped
        assert not psutil.pid_exists(new_pid)
        assert not rt.loader.registry.runtime_owners.leases("matrix")
