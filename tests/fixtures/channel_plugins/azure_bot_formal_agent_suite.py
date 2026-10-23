"""Unchanged official Azure ZIP to real Core Agent and native Connector."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import zipfile

import aiohttp
import psutil
import pytest

from azure_bot_formal_support import (
    APP,
    SERVICE,
    azure_host_guard,
    azure_sdk_runtime,
    formal_connector,
    rsa_material,
)
from extension_process_suite import runtime, eventually
from extension_sample import ROOT
from g2_actual_agent_suite import assert_host_and_reload
from real_host_runtime import bind_real_runtime

__all__ = [
    "azure_host_guard",
    "azure_sdk_runtime",
    "formal_connector",
    "rsa_material",
    "runtime",
]


def formal_source(directory, key, **_kwargs):
    from qwenpaw.plugins.official_channels import bundled_channel_source

    assert key == "azure_bot"
    with bundled_channel_source("azure-bot") as extracted:
        destination = Path(directory) / key
        shutil.copytree(extracted, destination)
    return destination


def assert_original_archive(rt):
    resources = ROOT / "src/qwenpaw/official_channels"
    index = json.loads((resources / "index.json").read_text())
    row = next(
        row for row in index["plugins"] if row["plugin_id"] == "azure-bot"
    )
    artifact = resources / row["filename"]
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == row["sha256"]
    members = {}
    with zipfile.ZipFile(artifact) as archive:
        for item in archive.infolist():
            if item.is_dir():
                continue
            relative = Path(item.filename).relative_to("azure-bot")
            data = archive.read(item)
            assert (rt.source / relative).read_bytes() == data
            assert (
                ROOT / "plugins/channel/azure_bot" / relative
            ).read_bytes() == data
            members[str(relative)] = hashlib.sha256(data).hexdigest()
    return {"zip": artifact.name, "sha256": row["sha256"], "members": members}


@pytest.mark.asyncio
async def test_official_azure_zip_authenticated_activity_real_agent_and_cleanup(
    runtime, azure_sdk_runtime, formal_connector, monkeypatch, tmp_path
):
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    rt = await runtime(
        "azure_bot",
        source_factory=formal_source,
        python_executable=azure_sdk_runtime.python,
        runtime_identity=azure_sdk_runtime.identity,
        app_id=APP,
        app_password="synthetic-azure-secret",
        tenant_id="test-tenant",
        http_host="127.0.0.1",
        http_port=port,
        access_control_dm=True,
    )
    assert rt.record.manifest.id == "azure-bot" != rt.key == "azure_bot"
    assert rt.channel._launch_spec.code_root == rt.record.source_path
    original = assert_original_archive(rt)
    old_pid = rt.process.health_snapshot()["pid"]
    host = await bind_real_runtime(rt, monkeypatch)
    assert not psutil.pid_exists(old_pid)
    await eventually(
        lambda: rt.process.health_snapshot()["platform_state"] == "connected"
    )
    health = rt.process.health_snapshot()
    pid = health["pid"]
    assert pid != os.getpid() and psutil.pid_exists(pid)
    leases = [
        lease
        for lease in rt.loader.registry.runtime_owners.leases("azure-bot")
        if lease.key.kind == "channel"
    ]
    assert len(leases) == 1
    assert rt.loader.registry.runtime_owners.resource(leases[0]) is rt.channel
    assert leases[0].generation == health["generation"]
    assert any(
        connection.status == psutil.CONN_LISTEN
        and connection.laddr.port == port
        for connection in psutil.Process(pid).net_connections(kind="tcp")
    )
    rt.channel._get_acl_store().add_to_whitelist(
        "azure_bot", "aad-user-123456"
    )
    native = "Azure native actual agent"
    body = {
        "type": "message",
        "id": "formal-activity-1",
        "channelId": "msteams",
        "serviceUrl": SERVICE,
        "from": {
            "id": "channel-user-000001",
            "aadObjectId": "aad-user-123456",
            "name": "Ada",
        },
        "recipient": {"id": "native-bot"},
        "conversation": {"id": "conversation-ABCDEFGHIJ"},
        "text": native,
    }
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=5)
    ) as client:
        async with client.post(
            f"http://127.0.0.1:{port}/api/messages",
            json=body,
            headers={"Authorization": "Bearer " + formal_connector.token()},
        ) as response:
            assert response.status == 200, await response.text()
    await eventually(
        lambda: len(formal_connector.requests) == 1 and len(host.calls) == 1
    )
    route, payload, authorization = formal_connector.requests[0]
    assert route == "/v3/conversations/conversation-ABCDEFGHIJ/activities"
    assert payload == {
        "type": "message",
        "from": {"id": "native-bot"},
        "text": "actual agent answer",
    }
    assert authorization == "Bearer local-issued-token"
    assert formal_connector.auth_requests == [
        "/v1/.well-known/openidconfiguration",
        "/keys",
    ]
    assert formal_connector.token_requests == [
        {
            "app_id": APP,
            "scopes": ["https://api.botframework.com/.default"],
            "pid": pid,
        }
    ]
    evidence = await assert_host_and_reload(
        rt, host, native, "azure_msteams#ABCDEFGHIJ", "Ada#123456"
    )
    assert rt.channel._get_acl_store().get_all_pending() == []
    assert rt.ws.requests[0].channel_meta["user_name"] == "Ada"
    assert_original_archive(rt)
    receipt = await rt.manager.stop_one("azure_bot")
    assert receipt.stopped and receipt.exited and not receipt.residual
    assert not psutil.pid_exists(pid)
    assert not rt.loader.registry.runtime_owners.leases("azure-bot")
    with socket.socket() as released:
        released.bind(("127.0.0.1", port))
    evidence.update(
        {
            "owner": "azure-bot",
            "key": rt.key,
            "worker_pid": pid,
            "actor_acl": "aad-user-123456",
            "port_released": port,
            "artifact": original,
            "sdk_packages": azure_sdk_runtime.packages,
        }
    )
    (tmp_path / "azure-formal-evidence.json").write_text(
        json.dumps(evidence, indent=2)
    )


@pytest.mark.asyncio
async def test_formal_restart_restores_authenticated_target_without_new_ingress(
    runtime, azure_sdk_runtime, formal_connector, monkeypatch
):
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    rt = await runtime(
        "azure_bot",
        source_factory=formal_source,
        python_executable=azure_sdk_runtime.python,
        runtime_identity=azure_sdk_runtime.identity,
        app_id=APP,
        app_password="synthetic-azure-secret",
        tenant_id="test-tenant",
        http_host="127.0.0.1",
        http_port=port,
        access_control_dm=True,
    )
    assert_original_archive(rt)
    host = await bind_real_runtime(rt, monkeypatch)
    await eventually(
        lambda: rt.process.health_snapshot()["platform_state"] == "connected"
    )
    rt.channel._get_acl_store().add_to_whitelist(
        "azure_bot", "aad-user-123456"
    )
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=5)
    ) as client:
        async with client.post(
            f"http://127.0.0.1:{port}/api/messages",
            json={
                "type": "message",
                "id": "before-restart",
                "channelId": "msteams",
                "serviceUrl": SERVICE,
                "from": {
                    "id": "channel-user-000001",
                    "aadObjectId": "aad-user-123456",
                    "name": "Ada",
                },
                "recipient": {"id": "native-bot"},
                "conversation": {"id": "conversation-ABCDEFGHIJ"},
                "text": "remember this authenticated target",
            },
            headers={"Authorization": "Bearer " + formal_connector.token()},
        ) as response:
            assert response.status == 200, await response.text()
    await eventually(
        lambda: len(formal_connector.requests) == 1 and len(host.calls) == 1
    )
    before = rt.process.health_snapshot()
    state_paths = list(
        (rt.ws.workspace_dir / "channel_state/azure_bot").glob("*/refs.json")
    )
    assert len(state_paths) == 1
    state = state_paths[0].read_bytes()
    refs = json.loads(state)
    assert refs["owner"]["app_id"] == APP
    target = "azure_msteams#ABCDEFGHIJ:Ada#123456"
    assert refs["refs"][target]["conversation_id"] == "conversation-ABCDEFGHIJ"
    receipt = await rt.manager.stop_one("azure_bot")
    assert receipt.stopped and receipt.exited and not receipt.residual
    assert not psutil.pid_exists(before["pid"])
    assert not rt.loader.registry.runtime_owners.leases("azure-bot")
    fresh = (await rt.manager.start_one("azure_bot", rt.ws.config)).channel
    process = fresh.channel_process
    await eventually(
        lambda: process.health_snapshot()["platform_state"] == "connected"
    )
    after = process.health_snapshot()
    assert after["generation"] > before["generation"]
    assert after["pid"] != before["pid"] and psutil.pid_exists(after["pid"])
    assert state_paths[0].read_bytes() == state
    await fresh.send(target, "proactive after restart")
    assert len(host.calls) == 1
    assert formal_connector.requests[1:] == [
        (
            "/v3/conversations/conversation-ABCDEFGHIJ/activities",
            {
                "type": "message",
                "from": {"id": "native-bot"},
                "text": "proactive after restart",
            },
            "Bearer local-issued-token",
        )
    ]
    assert [row["pid"] for row in formal_connector.token_requests] == [
        before["pid"],
        after["pid"],
    ]
    assert formal_connector.auth_requests == [
        "/v1/.well-known/openidconfiguration",
        "/keys",
    ]
    assert state_paths[0].read_bytes() == state
    receipt = await rt.manager.stop_one("azure_bot")
    assert receipt.stopped and receipt.exited and not receipt.residual
    assert not psutil.pid_exists(after["pid"])
    assert not rt.loader.registry.runtime_owners.leases("azure-bot")
    with socket.socket() as released:
        released.bind(("127.0.0.1", port))
