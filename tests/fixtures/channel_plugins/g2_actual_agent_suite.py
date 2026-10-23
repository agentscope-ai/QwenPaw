"""Two formal G2 ZIPs through actual Core Agent and public disk sessions."""

import hashlib
import json
import os
from pathlib import Path
import sys
import zipfile

import psutil
import pytest

from extension_process_suite import eventually, identity, runtime
from extension_sample import ROOT
from g2_lifecycle_suite import official_zip_source
from g2_official_process_suite import (
    broker,
    forbid_host_sdk_import,
    mattermost,
    request_text,
)
from real_host_runtime import bind_real_runtime


def worker_identity(rt, port, *, peer=None):
    """Observe live OS sockets and the real owner, never service-generated PID."""
    health = rt.process.health_snapshot()
    pid = health["pid"]
    assert pid != os.getpid() and psutil.pid_exists(pid)
    assert health["platform_state"] == "connected"
    leases = [
        lease
        for lease in rt.loader.registry.runtime_owners.leases(rt.key)
        if lease.key.kind == "channel"
    ]
    assert len(leases) == 1
    lease = leases[0]
    assert rt.loader.registry.runtime_owners.resource(lease) is rt.channel
    assert lease.instance_id == identity(rt)["instance_id"]
    assert lease.generation == health["generation"]
    connections = [
        connection
        for connection in psutil.Process(pid).net_connections(kind="tcp")
        if connection.status == psutil.CONN_ESTABLISHED
        and connection.raddr
        and connection.raddr.ip == "127.0.0.1"
        and connection.raddr.port == port
        and (peer is None or tuple(connection.laddr) == peer)
    ]
    assert connections, (health, port, peer)
    return {
        "pid": pid,
        "instance_id": lease.instance_id,
        "generation": lease.generation,
        "platform_state": health["platform_state"],
        "tcp": [
            {"local": list(row.laddr), "remote": list(row.raddr)}
            for row in connections
        ],
    }


def text_values(value):
    if isinstance(value, dict):
        if value.get("type") == "text" and isinstance(value.get("text"), str):
            yield value["text"]
        for child in value.values():
            yield from text_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from text_values(child)


async def assert_host_and_reload(rt, host, native, session_id, user_id, *, expected_parts=None):
    from qwenpaw.app.chats.session import SafeJSONSession, session_filename
    from qwenpaw.runtime._state_utils import StateProxy

    assert len(rt.ws.requests) == 1
    request = rt.ws.requests[0]
    assert (request.channel, request.session_id, request.user_id) == (
        rt.key, session_id, user_id
    )
    expected_parts = [native] if expected_parts is None else expected_parts
    expected_input = "\n".join(expected_parts)
    assert request_text(request) == expected_input
    assert len(host.calls) == 1 and host.calls[0]["pid"] == os.getpid()
    assert host.builds == [{
        "pid": os.getpid(), "session_id": session_id, "agent": "QwenPawAgent"
    }]
    model_user_texts = [
        text
        for message in host.calls[0]["messages"]
        if message.role == "user"
        for text in text_values(message.model_dump())
    ]
    assert model_user_texts == expected_parts
    path = rt.ws.workspace_dir / "sessions" / rt.key / session_filename(
        session_id, user_id
    )
    await eventually(path.is_file)
    proxy = StateProxy()
    # A fresh session object loads the production SessionSaveHook's disk state.
    await SafeJSONSession(str(path.parent.parent)).load_session_state(
        session_id=session_id,
        user_id=user_id,
        channel=rt.key,
        allow_not_exist=False,
        agent=proxy,
    )
    texts = list(text_values(proxy.data))
    assert texts == [*expected_parts, "actual agent answer"], proxy.data
    return {
        "host_pid": os.getpid(),
        "builds": host.builds,
        "model_calls": len(host.calls),
        "channel": rt.key,
        "session_id": session_id,
        "user_id": user_id,
        "native_text": native,
        "agent_input": expected_input,
        "session_texts": texts,
        "session_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def artifact_evidence(rt, tmp_path):
    assert rt.channel._launch_spec.code_root == rt.record.source_path
    assert rt.source.is_relative_to(rt.loader.plugin_dirs[0])
    assert rt.source != ROOT / "plugins/channel" / rt.key
    manifest = json.loads((rt.source / "plugin.json").read_text())
    artifact = tmp_path / "official-bundle" / (
        manifest["id"] + "-" + manifest["version"] + ".zip"
    )
    member_hashes = {}
    with zipfile.ZipFile(artifact) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            relative = Path(info.filename).relative_to(manifest["id"])
            packed = archive.read(info)
            assert (rt.source / relative).read_bytes() == packed
            assert (ROOT / "plugins/channel" / rt.key / relative).read_bytes() == packed
            member_hashes[str(relative)] = hashlib.sha256(packed).hexdigest()
    return {
        "name": artifact.name,
        "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "bytes": artifact.stat().st_size,
        "source_file_hashes": member_hashes,
    }


async def stop_and_record(rt, observation):
    pid = observation["worker"]["pid"]
    receipt = await rt.manager.stop_one(rt.key)
    assert receipt.stopped and receipt.exited and not receipt.residual
    assert not psutil.pid_exists(pid)
    assert await rt.manager.get_channel(rt.key) is None
    assert not rt.loader.registry.runtime_owners.leases(rt.key)
    assert not any(
        name.startswith(("qwenpaw_channel_mqtt", "qwenpaw_channel_mattermost", "paho"))
        for name in sys.modules
    )
    observation["worker_exited"] = True
    print("G2_ACTUAL_AGENT_EVIDENCE=" + json.dumps(observation, sort_keys=True))


@pytest.mark.asyncio
async def test_mqtt_formal_zip_real_agent_session_and_worker_exit(
    runtime, broker, monkeypatch, tmp_path
):
    rt = await runtime(
        "mqtt", source_factory=official_zip_source,
        host="127.0.0.1", port=broker.port, transport="tcp",
        subscribe_topic="in/+", publish_topic="out/{client_id}",
    )
    old_pid = rt.process.health_snapshot()["pid"]
    host = await bind_real_runtime(rt, monkeypatch)
    assert not psutil.pid_exists(old_pid)
    await eventually(lambda: len(broker.clients) == 1 and len(broker.subscriptions) == 2)
    worker = worker_identity(rt, broker.port, peer=broker.clients[0].getpeername())
    native = "MQTT native actual agent"
    broker.emit("in/actual-device", json.dumps({
        "text": native, "redirect_client_id": "actual-redirect"
    }))
    await eventually(lambda: len(broker.publishes) == 1 and len(host.calls) == 1)
    assert broker.publishes == [("out/actual-redirect", "actual agent answer", 2)]
    evidence = await assert_host_and_reload(
        rt, host, native, "mqtt:actual-redirect", "actual-redirect"
    )
    assert rt.ws.requests[0].channel_meta["client_id"] == "actual-redirect"
    evidence.update({"worker": worker, "artifact": artifact_evidence(rt, tmp_path),
                     "platform_output": broker.publishes})
    await stop_and_record(rt, evidence)
    await eventually(lambda: not broker.clients)


@pytest.mark.asyncio
async def test_mattermost_formal_zip_real_agent_session_and_worker_exit(
    runtime, mattermost, monkeypatch, tmp_path
):
    rt = await runtime(
        "mattermost", source_factory=official_zip_source,
        url=mattermost.url, bot_token="local-test-token",
    )
    old_pid = rt.process.health_snapshot()["pid"]
    host = await bind_real_runtime(rt, monkeypatch)
    assert not psutil.pid_exists(old_pid)
    await eventually(lambda: mattermost.has_connection)
    worker = worker_identity(rt, mattermost.http_port)
    native = "Mattermost native actual agent"
    mattermost.push_dm_post(
        text=native, channel_id="actual-dm", user_id="actual-human",
        post_id="actual-agent-post",
    )
    await eventually(lambda: len(mattermost.posts) == 1 and len(host.calls) == 1)
    assert mattermost.posts == [{
        "channel_id": "actual-dm", "message": "actual agent answer", "root_id": ""
    }]
    assert [body for method, path, body in mattermost.requests
            if method == "POST" and path == "/api/v4/posts"] == mattermost.posts
    assert any(headers.get("Authorization") == "Bearer local-test-token"
               for headers in mattermost.request_headers)
    evidence = await assert_host_and_reload(
        rt, host, native, "mattermost_dm:actual-dm", "actual-human",
        expected_parts=["[Recent 20 DM context messages]\n"
                        "[History ended, please answer the following questions "
                        "based on the above context]", native],
    )
    assert rt.ws.requests[0].channel_meta["mm_channel_id"] == "actual-dm"
    evidence.update({"worker": worker, "artifact": artifact_evidence(rt, tmp_path),
                     "platform_output": mattermost.posts})
    await stop_and_record(rt, evidence)
    await eventually(lambda: not mattermost.has_connection)
