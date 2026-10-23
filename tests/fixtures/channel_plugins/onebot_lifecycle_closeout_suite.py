"""OneBot-owned listeners: real workspaces and enabled rollback only."""

import asyncio
from contextlib import AsyncExitStack
import json
import os

import aiohttp
import psutil
import pytest

from onebot_formal_closeout_suite import (
    eventually,
    formal_onebot_source,
    incoming,
)
from real_host_runtime import bind_real_runtime

pytest_plugins = ["extension_process_suite"]


def endpoint(rt):
    value = rt.channel.endpoint_service.resolve()
    assert value is not None and value.endpoint.readiness == "ready"
    return value, f"http://127.0.0.1:{value.endpoint.port}/ws"


async def refresh(rt):
    rt.channel = await rt.manager.get_channel("onebot")
    rt.process = rt.channel.channel_process
    await eventually(
        lambda: rt.process.health_snapshot()["platform_state"] == "connected"
    )
    return rt.process.health_snapshot()["pid"]


async def roundtrip(ws, rt, number, prompt):
    await ws.send_json(incoming(number, prompt))
    frame = await asyncio.wait_for(ws.receive_json(), 8)
    assert frame["action"] == "send_private_msg"
    assert frame["params"] == {
        "user_id": 12345,
        "message": [{"type": "text", "data": {"text": "owned answer"}}],
    }
    await ws.send_json(
        {
            "retcode": 0,
            "data": {"message_id": number + 1000},
            "echo": frame["echo"],
        }
    )
    assert await rt.ws.task_tracker.wait_all_done(timeout=8)
    return frame


async def test_formal_two_workspace_listener_identity_and_stop(
    runtime, monkeypatch
):
    from extension_process_suite import identity
    from qwenpaw.channel_protocol.errors import RpcError

    first = await runtime(
        "onebot",
        source_factory=formal_onebot_source,
        ws_host="127.0.0.1",
        ws_port=0,
        access_token="first-token",
        workspace_name="first",
    )
    host_a = await bind_real_runtime(first, monkeypatch, reply="owned answer")
    second = await runtime(
        "onebot",
        existing_loader=first.loader,
        ws_host="127.0.0.1",
        ws_port=0,
        access_token="second-token",
        workspace_name="second",
    )
    old_identity = identity(second)
    old_endpoint, _ = endpoint(second)
    host_b = await bind_real_runtime(second, monkeypatch, reply="owned answer")
    pid_a, pid_b = await refresh(first), await refresh(second)
    assert len({pid_a, pid_b, os.getpid()}) == 3
    assert identity(second) != old_identity
    assert not second.channel.endpoint_service.is_current(old_endpoint)
    with pytest.raises(RpcError):
        await second.process.call(
            "channel.response.open",
            {**old_identity, "to_handle": "12345", "meta": {}},
        )
    ref_a, url_a = endpoint(first)
    ref_b, url_b = endpoint(second)
    assert ref_a.endpoint.port != ref_b.endpoint.port
    async with aiohttp.ClientSession() as client, AsyncExitStack() as stack:
        with pytest.raises(aiohttp.WSServerHandshakeError) as exc:
            await client.ws_connect(
                url_b, headers={"Authorization": "Bearer first-token"}
            )
        assert exc.value.status == 401
        ws_a = await stack.enter_async_context(
            client.ws_connect(
                url_a, headers={"Authorization": "Bearer first-token"}
            )
        )
        ws_b = await stack.enter_async_context(
            client.ws_connect(
                url_b, headers={"Authorization": "Bearer second-token"}
            )
        )
        await roundtrip(ws_a, first, 601, "only first workspace")
        await roundtrip(ws_b, second, 601, "only second workspace")
        for rt, host, own, other in (
            (first, host_a, "only first workspace", "only second workspace"),
            (second, host_b, "only second workspace", "only first workspace"),
        ):
            assert len(rt.ws.requests) == len(host.builds) == 1
            assert rt.ws.requests[0].session_id == "onebot:12345"
            assert rt.ws.requests[0].user_id == "12345"
            assert rt.ws.requests[0].input[0].content[0].text == own
            sessions = list((rt.ws.workspace_dir / "sessions").rglob("*.json"))
            assert len(sessions) == 1
            assert own in sessions[0].read_text()
            assert other not in sessions[0].read_text()
        # External model factory is process-global; the second helper observes
        # both actual Agent builds. Per-workspace builds stay exact.
        assert host_a.calls == [] and len(host_b.calls) == 2
        await first.manager.stop_all()
        await eventually(lambda: not psutil.pid_exists(pid_a))
        closed = await asyncio.wait_for(ws_a.receive(), 8)
        assert closed.type in {
            aiohttp.WSMsgType.CLOSE,
            aiohttp.WSMsgType.CLOSED,
        }
        assert first.channel.endpoint_service.resolve() is None
        assert not first.channel.endpoint_service.is_current(ref_a)
        assert second.channel.endpoint_service.is_current(ref_b)
        assert psutil.pid_exists(pid_b)
        await roundtrip(ws_b, second, 602, "second survives")
        assert len(first.ws.requests) == len(host_a.builds) == 1
        assert len(second.ws.requests) == len(host_b.builds) == 2
        assert len(host_b.calls) == 3
        await second.manager.stop_all()
        await eventually(lambda: not psutil.pid_exists(pid_b))
        assert second.channel.endpoint_service.resolve() is None
    print(
        "ONEBOT_WORKSPACES "
        + json.dumps(
            {
                "pids": [pid_a, pid_b],
                "ports": [ref_a.endpoint.port, ref_b.endpoint.port],
                "builds": [host_a.builds, host_b.builds],
            }
        ),
        flush=True,
    )


async def test_enabled_update_failure_restores_listener_session_and_reply(
    runtime, monkeypatch, tmp_path
):
    rt = await runtime(
        "onebot",
        source_factory=formal_onebot_source,
        ws_host="127.0.0.1",
        ws_port=0,
        access_token="rollback-token",
    )
    host = await bind_real_runtime(rt, monkeypatch, reply="owned answer")
    old_pid = await refresh(rt)
    old_endpoint, old_url = endpoint(rt)
    async with aiohttp.ClientSession() as client:
        async with client.ws_connect(
            old_url, headers={"Authorization": "Bearer rollback-token"}
        ) as ws:
            await roundtrip(ws, rt, 701, "before update")
        sessions = {
            p: p.read_bytes()
            for p in (rt.ws.workspace_dir / "sessions").rglob("*.json")
        }
        assert len(sessions) == 1
        assert all(b"before update" in value for value in sessions.values())
        installed = rt.source / "qwenpaw_channel_onebot/driver.py"
        original = installed.read_bytes()
        config = dict(rt.channel._launch_spec.config)
        candidate = formal_onebot_source(tmp_path / "update", "onebot")
        manifest_path = candidate / "plugin.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["version"] = "2.0.0"
        manifest_path.write_text(json.dumps(manifest))
        with (candidate / "qwenpaw_channel_onebot/driver.py").open("a") as f:
            f.write(
                "\n_OriginalDriver = OneBotDriver\n"
                "class OneBotDriver(_OriginalDriver):\n"
                "    async def start(self, config):\n"
                "        await super().start(config)\n"
                "        if config.get('enabled'):\n"
                "            raise RuntimeError('CONTROLLED_UPDATE_FAILURE')\n"
            )
        report = await rt.loader.lifecycle.reload(
            "onebot", new_source=candidate
        )
        assert not report.ok and report.errors
        assert installed.read_bytes() == original
        assert {p: p.read_bytes() for p in sessions} == sessions
        pid = await refresh(rt)
        assert pid != old_pid and not psutil.pid_exists(old_pid)
        assert (
            rt.channel.enabled
            and dict(rt.channel._launch_spec.config) == config
        )
        assert not rt.channel.endpoint_service.is_current(old_endpoint)
        _, url = endpoint(rt)
        async with client.ws_connect(
            url, headers={"Authorization": "Bearer rollback-token"}
        ) as ws:
            await roundtrip(ws, rt, 702, "after rollback")
        assert len(rt.ws.requests) == len(host.calls) == len(host.builds) == 2
        assert all(
            "before update" in p.read_text()
            and "after rollback" in p.read_text()
            for p in sessions
        )
        await rt.manager.stop_all()
        await eventually(lambda: not psutil.pid_exists(pid))
        assert rt.channel.endpoint_service.resolve() is None
