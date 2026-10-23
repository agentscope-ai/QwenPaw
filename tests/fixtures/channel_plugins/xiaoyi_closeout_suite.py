"""Formal unchanged XiaoYi package through real host/worker/Agent boundaries."""
import asyncio
import hashlib
import importlib.abc
import json
import os
from pathlib import Path
import shutil
import sys
import sysconfig

import pytest

from xiaoyi_native_support import gateway, inbound
from real_host_runtime import bind_real_runtime

pytest_plugins = ["extension_process_suite"]
ROOT = Path(__file__).resolve().parents[3]


def formal_source(directory, key, **_):
    from qwenpaw.plugins.official_channels import bundled_channel_source
    assert key == "xiaoyi"
    with bundled_channel_source("xiaoyi") as bundled:
        destination = directory / key
        shutil.copytree(bundled, destination)
        assert {str(p.relative_to(bundled)): p.read_bytes() for p in bundled.rglob("*") if p.is_file()} == {str(p.relative_to(destination)): p.read_bytes() for p in destination.rglob("*") if p.is_file()}
    return destination


async def wait_for(predicate):
    # Existing real-host fixture timeout; never widen old integration budgets.
    async with asyncio.timeout(8):
        while not predicate():
            await asyncio.sleep(0.01)


def settings(gateway):
    return dict(ak="local-ak", sk="local-sk", agent_id="local-agent", ws_url=gateway.primary, dependency_paths=(Path(sysconfig.get_paths()["purelib"]),))


@pytest.mark.asyncio
async def test_formal_zip_loader_worker_queue_runs_actual_agent_and_finishes_native_task(runtime, gateway, monkeypatch):
    class PrivateGuard(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.startswith("qwenpaw_channel_xiaoyi"):
                raise AssertionError("Private platform imported in host: " + fullname)
    guard = PrivateGuard()
    sys.meta_path.insert(0, guard)
    try:
        rt = await runtime("xiaoyi", source_factory=formal_source, **settings(gateway))
        host = await bind_real_runtime(rt, monkeypatch, reply="formal XiaoYi actual Agent answer")
        pid = rt.process.health_snapshot()["pid"]
        assert pid and pid != os.getpid()
        await wait_for(lambda: "primary" in gateway.connections and not gateway.connections["primary"].closed)
        assert set(gateway.connections) == {"primary"}
        assert any(frame.get("msgType") == "clawd_bot_init" for _, frame in gateway.frames)
        await gateway.push(inbound(text="hello from formal XiaoYi", session="formal-session", task="formal-task", message="formal-message"))
        await wait_for(lambda: any(result.get("final") is True for _, result in gateway.results()))
        assert len(rt.ws.requests) == 1
        request = rt.ws.requests[0]
        assert request.channel == "xiaoyi"
        assert request.user_id == "formal-session"
        assert request.session_id == "xiaoyi:formal-session"
        assert host.calls and all(call["pid"] == os.getpid() for call in host.calls)
        assert host.builds and all(item["agent"] == "QwenPawAgent" for item in host.builds)
        assert any(row.get("object") == "response" and row.get("status") == "completed" for row in host.events)
        results = [row for _, row in gateway.results()]
        texts = [part["text"] for result in results for part in result.get("artifact", {}).get("parts", []) if part.get("kind") == "text"]
        assert "formal XiaoYi actual Agent answer" in "".join(texts)
        assert results[-2]["kind"] == "status-update" and results[-2]["status"]["state"] == "completed" and results[-2]["final"] is False
        assert results[-1]["kind"] == "artifact-update" and results[-1]["final"] is True
        assert results[-1]["artifact"]["parts"] == [{"kind": "text", "text": ""}]
        assert not any(name.startswith("qwenpaw_channel_xiaoyi") for name in sys.modules)
    finally:
        sys.meta_path.remove(guard)


def test_legacy_from_env_values_and_defaults_retarget_to_public_reader(tmp_path):
    from qwenpaw.config.channel_env import read_channel_env
    values = read_channel_env("xiaoyi", {"XIAOYI_CHANNEL_ENABLED": "1", "XIAOYI_AK": "env_ak_value", "XIAOYI_SK": "env_sk_value", "XIAOYI_AGENT_ID": "env_agent_123", "XIAOYI_MEDIA_DIR": str(tmp_path / "media"), "XIAOYI_WS_URL": "ignored", "XIAOYI_TASK_TIMEOUT_MS": "17"})
    assert values["enabled"] is True
    assert values["ak"] == "env_ak_value"
    assert values["sk"] == "env_sk_value"
    assert values["agent_id"] == "env_agent_123"
    assert values["media_dir"] == str(tmp_path / "media")
    assert "ws_url" not in values and "task_timeout_ms" not in values
    defaults = read_channel_env("xiaoyi", {})
    assert defaults == {"enabled": False, "ak": "", "sk": "", "agent_id": "", "media_dir": ""}
    assert read_channel_env("xiaoyi", {"XIAOYI_CHANNEL_ENABLED": "true"})["enabled"] is False


def test_doctor_public_entry_keeps_both_hosts_and_timeout_without_legacy_import(monkeypatch):
    from qwenpaw.cli import doctor_connectivity
    from qwenpaw.config.config import XiaoYiConfig
    calls = []
    def tcp(host, port, timeout):
        calls.append((host, port, timeout))
        return "controlled-unreachable" if host == "116.63.174.231" else None
    monkeypatch.setattr(doctor_connectivity, "_tcp_check", tcp)
    result = doctor_connectivity._probe_xiaoyi("workspace-agent", XiaoYiConfig(), 2.5)
    assert calls == [("hag.cloud.huawei.com", 443, 2.5), ("116.63.174.231", 443, 2.5)]
    assert result == ["workspace-agent: xiaoyi: TCP 116.63.174.231:443 (backup) — controlled-unreachable"]
    assert not any(name.startswith("qwenpaw.app.channels.xiaoyi") for name in sys.modules)


@pytest.mark.asyncio
async def test_formal_two_workspaces_same_platform_account_isolate_workers_and_old_identity(runtime, gateway, monkeypatch):
    import psutil
    from qwenpaw.channel_protocol.errors import RpcError
    from extension_process_suite import identity

    first = await runtime("xiaoyi", source_factory=formal_source, workspace_name="xiaoyi-first", **settings(gateway))
    host_first = await bind_real_runtime(first, monkeypatch, reply="isolated actual reply")
    second_settings = settings(gateway)
    second_settings["ws_url"] = gateway.backup
    second = await runtime("xiaoyi", existing_loader=first.loader, workspace_name="xiaoyi-second", **second_settings)
    old_identity = identity(second)
    host_second = await bind_real_runtime(second, monkeypatch, reply="isolated actual reply")
    first.channel = await first.manager.get_channel("xiaoyi")
    first.process = first.channel.channel_process
    first_pid, second_pid = first.process.health_snapshot()["pid"], second.process.health_snapshot()["pid"]
    assert len({first_pid, second_pid, os.getpid()}) == 3
    assert identity(second) != old_identity
    await wait_for(lambda: all(name in gateway.connections and not gateway.connections[name].closed for name in ("primary", "backup")))
    with pytest.raises(RpcError):
        await second.process.call("channel.response.open", {**old_identity, "to_handle": "xiaoyi:shared-session", "meta": {"task_id": "stale-task"}})
    assert first.ws.requests == second.ws.requests == []
    await gateway.push(inbound(request="workspace-one", message="workspace-one", task="task-one", session="shared-session"), server="primary")
    await gateway.push(inbound(request="workspace-two", message="workspace-two", task="task-two", session="shared-session"), server="backup")
    await wait_for(lambda: sum(bool(row.get("final")) for _, row in gateway.results()) == 2)
    assert len(first.ws.requests) == len(second.ws.requests) == 1
    assert first.ws.requests[0].session_id == second.ws.requests[0].session_id == "xiaoyi:shared-session"
    assert host_first.builds and host_second.builds
    assert (first.ws.workspace_dir / "sessions").is_dir()
    assert (second.ws.workspace_dir / "sessions").is_dir()
    assert first.ws.workspace_dir != second.ws.workspace_dir
    await first.manager.stop_all()
    await wait_for(lambda: not psutil.pid_exists(first_pid))
    assert psutil.pid_exists(second_pid)
    assert not gateway.connections["backup"].closed
    await gateway.push(inbound(request="workspace-two-after-stop", message="workspace-two-after-stop", task="task-after-stop", session="shared-session"), server="backup")
    await wait_for(lambda: sum(bool(row.get("final")) for server, row in gateway.results() if server == "backup") == 2)
    assert len(first.ws.requests) == 1 and len(second.ws.requests) == 2


@pytest.mark.asyncio
async def test_formal_enabled_candidate_failure_rolls_back_source_and_actual_agent_delivery(runtime, gateway, monkeypatch, tmp_path):
    rt = await runtime("xiaoyi", source_factory=formal_source, **settings(gateway))
    host = await bind_real_runtime(rt, monkeypatch, reply="rollback actual answer")
    installed = rt.source / "qwenpaw_channel_xiaoyi/driver.py"
    original = installed.read_bytes()
    candidate = formal_source(tmp_path / "update", "xiaoyi")
    manifest_path = candidate / "plugin.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["version"] = "2.0.0"
    manifest_path.write_text(json.dumps(manifest))
    with (candidate / "qwenpaw_channel_xiaoyi/driver.py").open("a") as stream:
        stream.write('\n_OriginalDriver = XiaoYiDriver\nclass XiaoYiDriver(_OriginalDriver):\n    async def start(self, config):\n        if config.get("enabled"):\n            raise RuntimeError("CONTROLLED_ENABLED_CANDIDATE_FAILURE")\n        return await super().start(config)\n')
    report = await rt.loader.lifecycle.reload("xiaoyi", new_source=candidate)
    assert not report.ok and report.errors
    assert installed.read_bytes() == original
    current = await rt.manager.get_channel("xiaoyi")
    assert current is not None and current.enabled
    assert current.channel_process.health_snapshot()["pid"] != os.getpid()
    await wait_for(lambda: "primary" in gateway.connections and not gateway.connections["primary"].closed)
    await gateway.push(inbound(request="after-rollback", message="after-rollback", task="rollback-task", session="rollback-session"))
    await wait_for(lambda: any(row.get("final") is True for _, row in gateway.results()))
    assert len(rt.ws.requests) == 1
    assert host.builds and host.calls
    assert "rollback actual answer" in "".join(part["text"] for _, row in gateway.results() for part in row.get("artifact", {}).get("parts", []) if part.get("kind") == "text")


@pytest.mark.asyncio
@pytest.mark.parametrize("session,user,expected", [("xiaoyi:session_123", "user_123", "session_123"), ("other:session", "user_123", "user_123")])
async def test_original_proactive_target_native_destination_survives_generic_handle(runtime, gateway, session, user, expected):
    rt = await runtime("xiaoyi", source_factory=formal_source, **settings(gateway))
    target = rt.channel.to_handle_from_target(user_id=user, session_id=session)
    await rt.channel.send(target, "exact proactive route", {"task_id": "proactive-task", "message_id": "proactive-message", "server_name": "primary"})
    await wait_for(lambda: bool(gateway.results()))
    responses = [frame for _, frame in gateway.frames if frame.get("msgType") == "agent_response"]
    assert len(responses) == 3
    assert all(frame["sessionId"] == expected for frame in responses)
    assert all(frame["taskId"] == "proactive-task" for frame in responses)
    completion = json.loads(responses[1]["msgDetail"])["result"]
    final = json.loads(responses[2]["msgDetail"])["result"]
    assert completion["kind"] == "status-update" and completion["status"]["state"] == "completed" and completion["final"] is False
    assert final["kind"] == "artifact-update" and final["final"] is True
    assert final["artifact"]["parts"] == [{"kind": "text", "text": ""}]
    body = json.loads(responses[0]["msgDetail"])
    assert body["id"] == "proactive-message"
    assert body["result"]["artifact"]["parts"] == [{"kind": "text", "text": "exact proactive route"}]
    assert rt.ws.requests == []


@pytest.mark.asyncio
async def test_formal_acl_rejects_before_agent_but_allowed_actor_reaches_real_queue(runtime, gateway, monkeypatch):
    rt = await runtime("xiaoyi", source_factory=formal_source, access_control_dm=True, **settings(gateway))
    host = await bind_real_runtime(rt, monkeypatch, reply="allowed actual reply")
    assert rt.channel.access_control_dm is True
    assert rt.channel._launch_spec.config["access_control_dm"] is True
    store = rt.channel._get_acl_store()
    store.add_to_whitelist("xiaoyi", "allowed-session")
    assert store.is_whitelisted("xiaoyi", "allowed-session")
    assert not store.is_whitelisted("xiaoyi", "denied-session")
    await wait_for(lambda: "primary" in gateway.connections and not gateway.connections["primary"].closed)
    await gateway.push(inbound(request="denied", message="denied", session="denied-session", task="denied-task"))
    # A denial's normal native response is a causal barrier, not a sleep.
    await wait_for(lambda: any(frame.get("taskId") == "denied-task" for _, frame in gateway.frames))
    assert rt.ws.requests == [] and host.builds == [] and host.calls == []
    assert [(row["channel"], row["user_id"]) for row in store.get_all_pending()] == [("xiaoyi", "denied-session")]
    await gateway.push(inbound(request="allowed", message="allowed", session="allowed-session", task="allowed-task"))
    await wait_for(lambda: any(frame.get("taskId") == "allowed-task" and json.loads(frame.get("msgDetail", "{} ")).get("result", {}).get("final") is True for _, frame in gateway.frames if frame.get("msgType") == "agent_response"))
    assert len(rt.ws.requests) == 1 and rt.ws.requests[0].user_id == "allowed-session"
    assert host.builds and host.calls


@pytest.mark.asyncio
async def test_formal_uninstall_keeps_user_config_data_and_passive_public_api_without_worker(runtime, gateway, monkeypatch):
    import psutil
    from fastapi import FastAPI
    from httpx import AsyncClient, ASGITransport
    from qwenpaw.app.routers import config as routes
    from qwenpaw.config.config import load_agent_config, save_agent_config
    from qwenpaw.config.utils import load_config
    from qwenpaw.plugins.lifecycle import UnloadMode

    rt = await runtime("xiaoyi", source_factory=formal_source, **settings(gateway))
    await bind_real_runtime(rt, monkeypatch)
    print("UNINSTALL_STAGE runtime_bound", flush=True)
    profile = load_agent_config(rt.ws.agent_id)
    profile.channels = rt.ws._config.channels
    save_agent_config(rt.ws.agent_id, profile)
    agent_file = rt.ws.workspace_dir / "agent.json"
    channels_before = json.loads(agent_file.read_bytes())["channels"]
    business = rt.ws.workspace_dir / "media" / "keep-user-data.txt"
    business.parent.mkdir(exist_ok=True)
    business.write_bytes(b"user-owned-business-data")
    pid = rt.process.health_snapshot()["pid"]
    print("UNINSTALL_STAGE before_unload", flush=True)
    report = await rt.loader.lifecycle.unload("xiaoyi", UnloadMode.UNINSTALL)
    print("UNINSTALL_STAGE after_unload", flush=True)
    assert report.clean
    await wait_for(lambda: not psutil.pid_exists(pid))
    assert rt.loader.find_installed_plugin_dir("xiaoyi") is None
    assert "xiaoyi" in load_config().channel_plugin_state.uninstalled
    assert json.loads(agent_file.read_bytes())["channels"] == channels_before
    assert business.read_bytes() == b"user-owned-business-data"
    async def get_agent(_request):
        return rt.ws
    monkeypatch.setattr("qwenpaw.app.agent_context.get_agent_for_request", get_agent)
    app = FastAPI()
    app.state.plugin_loader = rt.loader
    app.include_router(routes.router)
    before_children = {p.pid for p in psutil.Process().children(recursive=True)}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        print("UNINSTALL_STAGE before_get", flush=True)
        response = await client.get("/config/channels/xiaoyi")
        print("UNINSTALL_STAGE after_get", flush=True)
        assert response.status_code == 200
        assert response.json()["ak"] == "local-ak" and response.json()["agent_id"] == "local-agent"
        print("UNINSTALL_STAGE before_schema", flush=True)
        schema = await client.get("/config/channels/schemas")
        print("UNINSTALL_STAGE after_schema", flush=True)
        assert schema.status_code == 200
        assert schema.json()["xiaoyi"]["availability"] == "missing_code"
    assert {p.pid for p in psutil.Process().children(recursive=True)} == before_children
    assert not any(name.startswith("qwenpaw_channel_xiaoyi") for name in sys.modules)


@pytest.mark.asyncio
async def test_raw_legacy_allowlist_fixture_projection_diagnostic(runtime, gateway, monkeypatch):
    rt = await runtime("xiaoyi", source_factory=formal_source, dm_policy="allowlist", allow_from=["allowed-session"], **settings(gateway))
    def observed():
        return {"policy": rt.channel.dm_policy, "access_control_dm": rt.channel.access_control_dm, "allow_from": sorted(rt.channel.allow_from), "launch": {key: rt.channel._launch_spec.config[key] for key in ("dm_policy", "allow_from", "access_control_dm")}}
    before = observed()
    await bind_real_runtime(rt, monkeypatch)
    after = observed()
    print("ACL_CONFIGURATION_DIAGNOSTIC", json.dumps({"before": before, "after": after}), flush=True)
    assert before == after
    assert before == {"policy": "allowlist", "access_control_dm": False, "allow_from": ["allowed-session"], "launch": {"dm_policy": "allowlist", "allow_from": ["allowed-session"], "access_control_dm": False}}
    # Constructor-only typed Config is not persisted-old-config migration.
    assert rt.ws.requests == []


import pytest_asyncio


@pytest_asyncio.fixture(autouse=True)
async def closeout_pending_task_diagnostics(request, tmp_path):
    """Bounded observation only; never cancels product work or changes budgets."""
    if "uninstall" not in request.node.name and "acl_rejects" not in request.node.name:
        yield
        return
    async def dump():
        for _ in range(3):
            await asyncio.sleep(8)
            rows = []
            for task in asyncio.all_tasks():
                frames = [{"file": frame.f_code.co_filename, "line": frame.f_lineno, "function": frame.f_code.co_name} for frame in task.get_stack()]
                chain, coro = [], task.get_coro()
                for _depth in range(16):
                    if coro is None:
                        break
                    frame = getattr(coro, "cr_frame", None) or getattr(coro, "gi_frame", None)
                    if frame is not None:
                        chain.append({"file": frame.f_code.co_filename, "line": frame.f_lineno, "function": frame.f_code.co_name})
                    coro = getattr(coro, "cr_await", None) or getattr(coro, "gi_yieldfrom", None)
                rows.append({"name": task.get_name(), "done": task.done(), "frames": frames, "await_chain": chain})
            with (tmp_path / "pending-tasks.jsonl").open("a") as out:
                out.write(json.dumps(rows) + "\n")
            print("PENDING_TASK_DUMP", str(tmp_path / "pending-tasks.jsonl"), flush=True)
    observer = asyncio.create_task(dump(), name="xiaoyi-test-bounded-observer")
    try:
        yield
    finally:
        observer.cancel()
        await asyncio.gather(observer, return_exceptions=True)


@pytest.mark.asyncio
async def test_missing_task_api_strict_but_ordinary_completed_response_tolerant(runtime, gateway):
    from qwenpaw.channel_protocol.errors import RpcError
    from qwenpaw.schemas import Message, TextContent
    rt = await runtime('xiaoyi', source_factory=formal_source, **settings(gateway))
    await wait_for(lambda: 'primary' in gateway.connections)
    with pytest.raises(RpcError):
        await rt.channel.send('session_123', 'Hello', {'_api_send': True})
    assert gateway.results() == []
    request = rt.channel.build_agent_request_from_native({'sender_id':'session_123','content_parts':[{'type':'text','text':'question'}],'meta':{}})
    target = rt.channel.get_to_handle_from_request(request)
    completed = Message(object='message', type='message', role='assistant', status='completed', content=[TextContent(text='Hello')])
    # Original missing-task ordinary send returns normally with no native effect.
    # Public completion is the actual replacement owner of ordinary tolerance.
    await rt.channel.on_event_message_completed(request, target, completed, {})
    assert gateway.results() == []


@pytest.mark.asyncio
@pytest.mark.parametrize('native_meta,expected', [({'session_id':'meta_session_123'}, 'meta_session_123'), ({}, 'user_123')])
async def test_request_meta_session_or_user_fallback_reaches_exact_native_target(runtime, gateway, native_meta, expected):
    rt = await runtime('xiaoyi', source_factory=formal_source, **settings(gateway))
    meta = {**native_meta, 'task_id':'task_123','message_id':'message_123'}
    request = rt.channel.build_agent_request_from_native({'sender_id':'user_123','content_parts':[{'type':'text','text':'question'}],'meta':meta})
    target = rt.channel.get_to_handle_from_request(request)
    await rt.channel.send(target, 'Hello', dict(request.channel_meta))
    await wait_for(lambda: len(gateway.results()) == 3)
    frames = [frame for _, frame in gateway.frames if frame.get('msgType') == 'agent_response']
    assert len(frames) == 3
    assert all(frame['sessionId'] == expected and frame['taskId'] == 'task_123' for frame in frames)
    assert json.loads(frames[0]['msgDetail'])['result']['artifact']['parts'] == [{'kind':'text','text':'Hello'}]
    assert json.loads(frames[1]['msgDetail'])['result']['status']['state'] == 'completed'
    assert json.loads(frames[2]['msgDetail'])['result']['final'] is True
