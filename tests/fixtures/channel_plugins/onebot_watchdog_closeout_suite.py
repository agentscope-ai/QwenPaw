"""Native listener recovery; only endpoint RPC replies are controlled."""

import socket

import aiohttp
import pytest

from onebot_native_suite import driver_at, message, until, ws_url


async def test_real_dynamic_rebind_reconciles_before_and_after_apply(tmp_path):
    async with driver_at(tmp_path) as (driver, peer, identity):
        platform = driver._platform
        original_call = peer.call
        faults = ["before_apply", "after_apply"]
        attempts = []

        async def transient(method, params):
            if method == "ingress.endpoint.update":
                attempts.append(dict(params))
                if faults:
                    fault = faults.pop(0)
                    if fault == "after_apply":
                        await original_call(method, params)
                    raise RuntimeError(fault)
            return await original_call(method, params)

        peer.call = transient
        await platform._site.stop()
        with pytest.raises(RuntimeError, match="after_apply"):
            await platform._watchdog_iteration()
        assert faults == []
        assert platform.health_snapshot()["platform_rebind_total"] == 1
        assert platform.health_snapshot()["endpoint_publication_pending"]
        assert not platform.health_snapshot()["accepting"]
        assert attempts[0]["readiness"] == "degraded"
        assert attempts[1]["readiness"] == "ready"
        rebound = platform.listen_port
        assert rebound is not None
        await platform._watchdog_iteration()
        assert attempts[2] == attempts[1]
        assert attempts[2]["port"] == rebound
        assert attempts[2]["generation"] == identity["generation"]
        assert platform.health_snapshot()["platform_rebind_total"] == 1
        assert not platform.health_snapshot()["endpoint_publication_pending"]
        assert platform.health_snapshot()["accepting"]
        assert not platform._watchdog_task.done()
        async with aiohttp.ClientSession() as client:
            async with client.ws_connect(ws_url(platform)) as ws:
                await ws.send_json(message(701))
                await until(lambda: len(peer.batches) == 1)
                assert (
                    peer.batches[0]["events"][0]["event_id"]
                    == "onebot:message:701"
                )


async def test_real_explicit_port_conflict_recovers_on_owner_release(tmp_path):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocker:
        blocker.bind(("127.0.0.1", 0))
        blocker.listen()
        port = blocker.getsockname()[1]
        async with driver_at(tmp_path, ws_port=port) as (
            driver,
            peer,
            identity,
        ):
            platform = driver._platform
            assert platform.listen_port is None
            assert peer.endpoints[-1][0] == "ingress.endpoint.register"
            assert peer.endpoints[-1][1]["readiness"] == "degraded"
            assert peer.endpoints[-1][1]["port"] == port
            blocker.close()
            await platform._watchdog_iteration()
            assert platform.listen_port == port
            assert platform.health_snapshot()["platform_rebind_total"] == 1
            assert peer.endpoints[-1][0] == "ingress.endpoint.update"
            assert peer.endpoints[-1][1]["readiness"] == "ready"
            assert peer.endpoints[-1][1]["port"] == port
            async with aiohttp.ClientSession() as client:
                async with client.ws_connect(ws_url(platform)):
                    pass
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as released:
            released.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            released.bind(("127.0.0.1", port))


async def test_unregistered_site_does_not_hide_runner_cleanup_failure(
    tmp_path, monkeypatch
):
    async with driver_at(tmp_path) as (driver, peer, identity):
        platform = driver._platform
        site, runner = platform._site, platform._runner
        port = platform.listen_port
        await site.stop()
        assert site not in runner.sites
        assert site._server is not None
        cleanup = type(runner).cleanup
        calls = []

        async def fail_once(instance):
            if instance is runner:
                calls.append(instance)
                if len(calls) == 1:
                    raise RuntimeError("CONTROLLED_RUNNER_CLEANUP_FAILURE")
            await cleanup(instance)

        monkeypatch.setattr(type(runner), "cleanup", fail_once)
        with pytest.raises(
            RuntimeError, match="ONEBOT_LISTENER_STOP_INCOMPLETE"
        ) as failure:
            await platform._stop_ws_server()
        assert (
            str(failure.value.__cause__) == "CONTROLLED_RUNNER_CLEANUP_FAILURE"
        )
        assert calls == [runner]
        assert platform._runner is runner
        assert driver._platform is platform
        assert platform._site is None
        assert not platform.health_snapshot()["accepting"]
        assert not any(
            method == "ingress.endpoint.unregister"
            for method, _ in peer.endpoints
        )
        await driver.stop()
        assert calls == [runner, runner]
        assert driver._platform is None
        assert platform._runner is None
        assert platform.listen_port is None
        assert peer.endpoints[-1] == ("ingress.endpoint.unregister", identity)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", port))
