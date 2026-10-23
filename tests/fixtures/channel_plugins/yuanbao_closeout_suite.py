"""Actual released Yuanbao ZIP through worker/Core/Agent/session."""

import asyncio
import json
import os
from pathlib import Path
import shutil
import sys
import time

import psutil
import pytest

from real_host_runtime import bind_real_runtime
from extension_process_suite import eventually, identity
from yuanbao_closeout_support import (
    forbid_yuanbao_host,
    official_yuanbao_zip,
    runtime,
    yuanbao_gateway,
)

__all__ = ["forbid_yuanbao_host", "runtime", "yuanbao_gateway"]


@pytest.mark.asyncio
async def test_formal_yuanbao_zip_actual_agent_session_target_map_and_stop(
    runtime, yuanbao_gateway, monkeypatch, tmp_path
):
    from qwenpaw.runtime._state_utils import StateProxy

    gateway = await yuanbao_gateway()
    parent = psutil.Process()
    before = {"rss": parent.memory_info().rss, "threads": parent.num_threads()}
    started = time.monotonic()
    rt = await runtime(
        "yuanbao",
        source_factory=official_yuanbao_zip,
        app_id="local-app",
        app_secret="local-secret",
        api_domain=gateway.base,
        ws_url=gateway.ws_url,
        bot_prefix="[元宝] ",
    )
    host = await bind_real_runtime(
        rt, monkeypatch, reply="formal yuanbao answer"
    )
    await gateway.control(
        "push", msg_id="formal-agent-message", text="formal inbound"
    )
    async with asyncio.timeout(8):
        while not (state := await gateway.control("state"))["sends"]:
            await asyncio.sleep(0.01)
    assert host.calls and host.calls[0]["pid"] == os.getpid()
    assert len(host.builds) == 1
    assert host.builds[0]["agent"] == "QwenPawAgent"
    assert host.builds[0]["session_id"] == "12345678"
    assert state["sends"][-1]["body"]["toAccount"] == "native-user-12345678"
    assert state["sends"][-1]["body"]["msgBody"] == [
        {
            "msgType": "TIMTextElem",
            "msgContent": {"text": "[元宝]   formal yuanbao answer"},
        }
    ]
    snapshot = StateProxy()
    await host.session.load_session_state(
        session_id="12345678",
        user_id="灰#5678",
        channel="yuanbao",
        agent=snapshot,
    )
    serialized = json.dumps(snapshot.data, ensure_ascii=False)
    assert (
        "formal inbound" in serialized
        and "formal yuanbao answer" in serialized
    )
    mapping = json.loads(
        (rt.ws.workspace_dir / "yuanbao_sessions.json").read_text()
    )
    assert mapping["12345678"]["sender_id"] == "native-user-12345678"
    pid = rt.process.health_snapshot()["pid"]
    assert pid != os.getpid() and pid != gateway.pid
    worker = psutil.Process(pid)
    metrics = {
        "scope": (
            "one actual ZIP/host Agent observation; "
            "no baseline reduction claim"
        ),
        "parent_before": before,
        "parent_pid": parent.pid,
        "parent_rss": parent.memory_info().rss,
        "parent_threads": parent.num_threads(),
        "workers": [
            {
                "pid": pid,
                "rss": worker.memory_info().rss,
                "threads": worker.num_threads(),
            }
        ],
        "external_gateway_pid_excluded_from_product_workers": gateway.pid,
        "seconds": time.monotonic() - started,
    }
    result = await rt.manager.stop_one("yuanbao")
    assert result.stopped and not psutil.pid_exists(pid)
    assert (await gateway.control("state"))["open_connections"] == 0
    (tmp_path / "yuanbao-actual-host-metrics.json").write_text(
        json.dumps(metrics, indent=2)
    )


@pytest.mark.asyncio
async def test_real_legacy_map_lock_does_not_block_worker_event_loop(
    runtime, yuanbao_gateway, monkeypatch, tmp_path
):
    gateway = await yuanbao_gateway()
    rt = await runtime(
        "yuanbao",
        source_factory=official_yuanbao_zip,
        app_id="local-app",
        app_secret="local-secret",
        api_domain=gateway.base,
        ws_url=gateway.ws_url,
    )
    host = await bind_real_runtime(rt, monkeypatch, reply="after lock release")
    await eventually(
        lambda: rt.process.health_snapshot()["platform_state"] == "connected"
    )
    map_path = rt.ws.workspace_dir / "yuanbao_sessions.json"
    legacy = {"legacy": {"opaque": "must survive merge"}}
    map_path.write_text(json.dumps(legacy))
    opened = await rt.process.call(
        "channel.response.open",
        {
            **identity(rt),
            "to_handle": "probe",
            "meta": {"chat_type": "c2c", "raw_sender_id": "native-probe"},
        },
        timeout=1,
    )
    params = {**identity(rt), "response_handle": opened["response_handle"]}
    baseline = await rt.process.call(
        "channel.response.describe", params, timeout=1
    )
    assert baseline["prepare"] is True
    ready = tmp_path / "legacy-lock-held"
    holder = await asyncio.create_subprocess_exec(
        sys.executable,
        "-I",
        str(Path(__file__).with_name("yuanbao_closeout_lock_holder.py")),
        str(map_path) + ".lock",
        str(ready),
        stdin=asyncio.subprocess.PIPE,
    )
    failure = None
    observation = {
        "worker_pid": rt.process.health_snapshot()["pid"],
        "holder_pid": holder.pid,
    }
    try:
        await eventually(ready.exists)
        assert int(ready.read_text()) == holder.pid
        await gateway.control(
            "push", msg_id="map-lock-message", text="blocked map"
        )
        async with asyncio.timeout(8):
            while not any(
                row["head"].get("cmdType") == 3
                for row in (await gateway.control("state"))["frames"]
            ):
                await asyncio.sleep(0.01)
        started = time.monotonic()
        try:
            policy = await rt.process.call(
                "channel.response.describe", params, timeout=1
            )
            assert policy == baseline
        except Exception as error:
            failure = error
        observation["held_lock_rpc_seconds"] = time.monotonic() - started
        observation["held_lock_rpc_error"] = (
            type(failure).__name__ if failure else None
        )
        observation["legacy_map_unchanged_while_held"] = (
            json.loads(map_path.read_text()) == legacy
        )
        assert observation["legacy_map_unchanged_while_held"]
    finally:
        holder.stdin.write(b"x")
        await holder.stdin.drain()
        holder.stdin.close()
        await asyncio.wait_for(holder.wait(), 3)
    assert holder.returncode == 0 and not psutil.pid_exists(holder.pid)
    assert (
        await rt.process.call("channel.response.describe", params, timeout=1)
        == baseline
    )
    await eventually(lambda: bool(host.calls))
    data = json.loads(map_path.read_text())
    assert data["legacy"] == legacy["legacy"]
    assert data["12345678"]["msg_id"] == "map-lock-message"
    receipt = await rt.manager.stop_one("yuanbao")
    assert receipt.stopped and not psutil.pid_exists(observation["worker_pid"])
    (tmp_path / "yuanbao-map-lock-observation.json").write_text(
        json.dumps(observation, indent=2)
    )
    assert failure is None, observation


async def wait_native_sends(gateway, count):
    async with asyncio.timeout(8):
        while True:
            state = await gateway.control("state")
            if len(state["sends"]) >= count:
                return state
            await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_stop_cancels_pending_map_lock_before_holder_releases(
    runtime, yuanbao_gateway, monkeypatch, tmp_path
):
    gateway = await yuanbao_gateway()
    rt = await runtime(
        "yuanbao",
        source_factory=official_yuanbao_zip,
        app_id="local-app",
        app_secret="local-secret",
        api_domain=gateway.base,
        ws_url=gateway.ws_url,
    )
    host = await bind_real_runtime(rt, monkeypatch)
    pid = rt.process.health_snapshot()["pid"]
    opened = await rt.process.call(
        "channel.response.open",
        {
            **identity(rt),
            "to_handle": "stop-probe",
            "meta": {"chat_type": "c2c", "raw_sender_id": "native-probe"},
        },
        timeout=1,
    )
    path = rt.ws.workspace_dir / "yuanbao_sessions.json"
    original = b'{"legacy":{"opaque":"keep"}}'
    path.write_bytes(original)
    ready = tmp_path / "stop-lock-held"
    holder = await asyncio.create_subprocess_exec(
        sys.executable,
        "-I",
        str(Path(__file__).with_name("yuanbao_closeout_lock_holder.py")),
        str(path) + ".lock",
        str(ready),
        stdin=asyncio.subprocess.PIPE,
    )
    try:
        await eventually(ready.exists)
        assert int(ready.read_text()) == holder.pid
        await gateway.control(
            "push", msg_id="cancel-map-write", text="never admitted"
        )
        async with asyncio.timeout(8):
            while not any(
                row["head"].get("cmdType") == 3
                for row in (await gateway.control("state"))["frames"]
            ):
                await asyncio.sleep(0.01)
        # The handler cannot publish Core ingress before its map write. A
        # subsequent real RPC gives that queued handler an event-loop turn.
        await rt.process.call(
            "channel.response.describe",
            {**identity(rt), "response_handle": opened["response_handle"]},
            timeout=1,
        )
        assert not host.calls and path.read_bytes() == original
        receipt = await rt.manager.stop_one("yuanbao")
        assert receipt.stopped and receipt.exited and not receipt.forced
        assert receipt.residual == () and receipt.returncode == 0
        assert not psutil.pid_exists(pid)
        assert holder.returncode is None and psutil.pid_exists(holder.pid)
        assert await rt.manager.get_channel("yuanbao") is None
        state = await gateway.control("state")
        assert state["open_connections"] == 0 and not state["sends"]
        assert not host.calls and path.read_bytes() == original
        assert not list(path.parent.glob(".yuanbao-sessions-*"))
    finally:
        holder.stdin.write(b"x")
        await holder.stdin.drain()
        holder.stdin.close()
        await asyncio.wait_for(holder.wait(), 3)
    assert holder.returncode == 0 and not psutil.pid_exists(holder.pid)
    assert path.read_bytes() == original and not psutil.pid_exists(pid)


@pytest.mark.asyncio
async def test_formal_two_workspaces_disable_and_enabled_activation_rollback(
    runtime, yuanbao_gateway, monkeypatch, tmp_path
):
    from qwenpaw.agents import model_factory
    from real_host_runtime import LocalModel

    gateway_a, gateway_b = await yuanbao_gateway("A"), await yuanbao_gateway(
        "B"
    )
    first = await runtime(
        "yuanbao",
        source_factory=official_yuanbao_zip,
        workspace_name="A",
        app_id="local-app",
        app_secret="local-secret",
        api_domain=gateway_a.base,
        ws_url=gateway_a.ws_url,
    )
    host_a = await bind_real_runtime(first, monkeypatch)
    second = await runtime(
        "yuanbao",
        existing_loader=first.loader,
        workspace_name="B",
        app_id="local-app",
        app_secret="local-secret",
        api_domain=gateway_b.base,
        ws_url=gateway_b.ws_url,
    )
    host_b = await bind_real_runtime(second, monkeypatch)
    # The second binding toggles the shared plugin and replaces A's real proxy.
    first.channel = await first.manager.get_channel("yuanbao")
    first.process = first.channel.channel_process
    # Both genuine Agent builds use one external model boundary. The helper's
    # per-call provider stub would otherwise point both workspaces at the last
    # fixture's call ledger; session/manager/Agent implementations stay real.
    calls = []
    model = LocalModel(calls, "isolated actual answer")
    monkeypatch.setattr(
        model_factory,
        "create_model_and_formatter",
        lambda **_kw: (model, model.formatter),
    )
    for rt in (first, second):
        await eventually(
            lambda: rt.process.health_snapshot()["platform_state"]
            == "connected"
        )
    await gateway_a.control("push", msg_id="scope-a", text="only workspace A")
    await gateway_b.control("push", msg_id="scope-b", text="only workspace B")
    await wait_native_sends(gateway_a, 1)
    await wait_native_sends(gateway_b, 1)
    assert len(calls) == 2
    assert len(host_a.builds) == len(host_b.builds) == 1
    for rt, expected, forbidden in (
        (first, "only workspace A", "only workspace B"),
        (second, "only workspace B", "only workspace A"),
    ):
        await eventually(
            lambda: bool(
                list((rt.ws.workspace_dir / "sessions/yuanbao").glob("*.json"))
            )
        )
        data = next(
            (rt.ws.workspace_dir / "sessions/yuanbao").glob("*.json")
        ).read_text()
        assert expected in data and forbidden not in data
    assert (
        json.loads(
            (first.ws.workspace_dir / "yuanbao_sessions.json").read_text()
        )["12345678"]["msg_id"]
        == "scope-a"
    )
    assert (
        json.loads(
            (second.ws.workspace_dir / "yuanbao_sessions.json").read_text()
        )["12345678"]["msg_id"]
        == "scope-b"
    )
    pid_a = first.process.health_snapshot()["pid"]
    pid_b = second.process.health_snapshot()["pid"]
    assert pid_a != pid_b
    first.ws._config.channels.yuanbao.enabled = False
    # A real workspace config reload stops its old Manager. project_workspace
    # only projects startup intents; mutating this fixture's config cannot
    # itself reconcile an already-current token.
    stopped_a = await first.manager.stop_one("yuanbao")
    assert stopped_a.stopped and stopped_a.exited
    assert not psutil.pid_exists(pid_a) and psutil.pid_exists(pid_b)
    assert (await gateway_a.control("state"))["open_connections"] == 0
    await gateway_b.control(
        "push", msg_id="scope-b-after-disable", text="B survives A disable"
    )
    await wait_native_sends(gateway_b, 2)
    old_config = second.ws.config.channels.yuanbao.model_dump()
    artifact_state = second.ws.workspace_dir / "original-business-data.bin"
    artifact_state.write_bytes(b"preserve business state")
    candidate = tmp_path / "candidate"
    shutil.copytree(
        second.source,
        candidate,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    manifest_path = candidate / "plugin.json"
    manifest = json.loads(manifest_path.read_text())
    original_version = manifest["version"]
    manifest["version"] = "99.0.0"
    manifest_path.write_text(json.dumps(manifest))
    await gateway_b.control(
        "activation",
        manifest_path=str(second.source / "plugin.json"),
        old_pid=pid_b,
        fail_version="99.0.0",
    )
    report = await second.loader.lifecycle.reload(
        "yuanbao", new_source=candidate
    )
    assert not report.ok and report.errors and not report.needs_restart
    state = await gateway_b.control("state")
    observations = state["activation_observations"]
    assert any(row["version"] == "99.0.0" for row in observations)
    assert all(not row["old_worker_alive"] for row in observations)
    assert (
        json.loads((second.source / "plugin.json").read_text())["version"]
        == original_version
    )
    current = await second.manager.get_channel("yuanbao")
    current_process = current.channel_process
    new_pid = current_process.health_snapshot()["pid"]
    assert new_pid != pid_b and not psutil.pid_exists(pid_b)
    assert psutil.pid_exists(new_pid)
    assert second.ws.config.channels.yuanbao.model_dump() == old_config
    assert artifact_state.read_bytes() == b"preserve business state"
    assert await first.manager.get_channel("yuanbao") is None
    await gateway_b.control(
        "push",
        msg_id="after-real-rollback",
        text="restored old version business",
    )
    await wait_native_sends(gateway_b, 3)
    assert len(host_b.builds) == 3
    await second.loader.lifecycle.set_enabled("yuanbao", False)
    assert not psutil.pid_exists(new_pid)
    assert (await gateway_b.control("state"))["open_connections"] == 0
    assert first.ws.config.channels.yuanbao.enabled is False
    assert second.ws.config.channels.yuanbao.enabled is True
    assert artifact_state.read_bytes() == b"preserve business state"


@pytest.mark.asyncio
async def test_formal_group_session_agent_reply_and_kickout(
    runtime, yuanbao_gateway, monkeypatch
):
    gateway = await yuanbao_gateway()
    rt = await runtime(
        "yuanbao",
        source_factory=official_yuanbao_zip,
        app_id="local-app",
        app_secret="local-secret",
        api_domain=gateway.base,
        ws_url=gateway.ws_url,
        require_mention=False,
    )
    host = await bind_real_runtime(
        rt, monkeypatch, reply="actual group answer"
    )
    await gateway.control(
        "push",
        group="group456",
        msg_id="formal-group",
        text="actual group inbound",
    )
    state = await wait_native_sends(gateway, 1)
    assert len(host.builds) == 1
    assert host.builds[0]["agent"] == "QwenPawAgent"
    assert host.builds[0]["session_id"] == "group456"
    assert rt.ws.requests[0].session_id == "group456"
    assert state["sends"][0]["body"]["groupCode"] == "group456"
    assert state["sends"][0]["body"]["msgBody"] == [
        {
            "msgType": "TIMTextElem",
            "msgContent": {"text": "actual group answer"},
        }
    ]
    pid = rt.process.health_snapshot()["pid"]
    connections = state["connections"]
    await gateway.control("kickout")
    await eventually(
        lambda: rt.process.health_snapshot()["platform_state"]
        == "disconnected"
    )
    state = await gateway.control("state")
    assert state["open_connections"] == 0
    assert state["connections"] == connections
    assert psutil.pid_exists(pid)  # Control frame does not crash its owner.
    receipt = await rt.manager.stop_one("yuanbao")
    assert receipt.stopped and receipt.exited and not psutil.pid_exists(pid)
