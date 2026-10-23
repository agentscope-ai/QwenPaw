"""Additional Azure owner/generation boundaries using real shared processes."""
import json
import socket

import aiohttp
import psutil
import pytest

from azure_bot_formal_agent_suite import formal_source, assert_original_archive
from azure_bot_formal_support import (
    APP,
    SERVICE,
    azure_host_guard,
    azure_sdk_runtime,
    formal_connector,
    rsa_material,
)
from extension_process_suite import runtime, eventually, identity
from real_host_runtime import bind_real_runtime

__all__ = [
    "azure_host_guard",
    "azure_sdk_runtime",
    "formal_connector",
    "rsa_material",
    "runtime",
]


async def create(runtime, sdk, **kwargs):
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    rt = await runtime(
        "azure_bot",
        source_factory=formal_source,
        python_executable=sdk.python,
        runtime_identity=sdk.identity,
        app_id=APP,
        app_password="synthetic-azure-secret",
        tenant_id="test-tenant",
        http_host="127.0.0.1",
        http_port=port,
        access_control_dm=True,
        **kwargs,
    )
    return rt, port


async def inbound(port, connector, event_id, conversation):
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=5)
    ) as client:
        async with client.post(
            f"http://127.0.0.1:{port}/api/messages",
            json={
                "type": "message",
                "id": event_id,
                "channelId": "msteams",
                "serviceUrl": SERVICE,
                "from": {
                    "id": "channel-user-000001",
                    "aadObjectId": "aad-user-123456",
                    "name": "Ada",
                },
                "recipient": {"id": "native-bot"},
                "conversation": {"id": conversation},
                "text": event_id,
            },
            headers={"Authorization": "Bearer " + connector.token()},
        ) as response:
            assert response.status == 200, await response.text()


@pytest.mark.asyncio
async def test_two_formal_workspaces_keep_owners_and_reject_old_generation(
    runtime,
    azure_sdk_runtime,
    formal_connector,
    monkeypatch,
):
    from qwenpaw.channel_protocol.errors import RpcError

    first, first_port = await create(
        runtime, azure_sdk_runtime, workspace_name="azure-A"
    )
    first_host = await bind_real_runtime(first, monkeypatch)
    second, second_port = await create(
        runtime,
        azure_sdk_runtime,
        existing_loader=first.loader,
        workspace_name="azure-B",
    )
    second_host = await bind_real_runtime(second, monkeypatch)
    # Binding the second real Runtime performs a real global disable/re-enable;
    # resolve the newly projected first channel rather than retaining its old proxy.
    first.channel = await first.manager.get_channel("azure_bot")
    first.process = first.channel.channel_process
    for rt in (first, second):
        rt.record = rt.loader.get_loaded_plugin("azure-bot")
    for rt in (first, second):
        await eventually(
            lambda rt=rt: rt.process.health_snapshot()["platform_state"]
            == "connected"
        )
        rt.channel._get_acl_store().add_to_whitelist(
            "azure_bot", "aad-user-123456"
        )
        assert_original_archive(rt)
    pids = [rt.process.health_snapshot()["pid"] for rt in (first, second)]
    assert pids[0] != pids[1] and all(psutil.pid_exists(pid) for pid in pids)
    assert first.record is second.record
    owners = first.loader.registry.runtime_owners
    leases = [
        lease
        for lease in owners.leases("azure-bot")
        if lease.key.kind == "channel"
    ]
    assert len(leases) == 2
    assert {id(owners.resource(lease)) for lease in leases} == {
        id(first.channel),
        id(second.channel),
    }
    await inbound(
        first_port, formal_connector, "workspace-A", "conversation-A"
    )
    await inbound(
        second_port, formal_connector, "workspace-B", "conversation-B"
    )
    await eventually(
        lambda: len(formal_connector.requests) == 2
        and first_host.builds
        and second_host.builds
    )
    old_identity = identity(first)
    assert (await first.manager.stop_one("azure_bot")).stopped
    assert not psutil.pid_exists(pids[0]) and psutil.pid_exists(pids[1])
    await inbound(
        second_port, formal_connector, "B-after-A-stop", "conversation-B"
    )
    await eventually(lambda: len(formal_connector.requests) == 3)
    assert (
        formal_connector.requests[-1][0]
        == "/v3/conversations/conversation-B/activities"
    )
    fresh = (
        await first.manager.start_one("azure_bot", first.ws.config)
    ).channel
    await eventually(
        lambda: fresh.channel_process.health_snapshot()["platform_state"]
        == "connected"
    )
    assert fresh._launch_spec.generation > old_identity["generation"]
    with pytest.raises(RpcError) as error:
        await fresh.channel_process.call(
            "channel.response.open",
            {
                **old_identity,
                "to_handle": "azure_msteams#ersation-A:Ada#123456",
                "meta": {},
            },
        )
    assert error.value.data["reason_code"] == "STALE_GENERATION"
    assert len(formal_connector.requests) == 3
    assert (await second.manager.stop_one("azure_bot")).stopped
    assert not psutil.pid_exists(pids[1])
    assert psutil.pid_exists(fresh.channel_process.health_snapshot()["pid"])
    assert (await first.manager.stop_one("azure_bot")).stopped
    assert not owners.leases("azure-bot")
    for port in (first_port, second_port):
        with socket.socket() as released:
            released.bind(("127.0.0.1", port))


@pytest.mark.asyncio
async def test_bad_azure_update_preserves_owner_payload_and_live_agent(
    runtime,
    azure_sdk_runtime,
    formal_connector,
    monkeypatch,
    tmp_path,
):
    rt, port = await create(runtime, azure_sdk_runtime)
    host = await bind_real_runtime(rt, monkeypatch)
    await eventually(
        lambda: rt.process.health_snapshot()["platform_state"] == "connected"
    )
    rt.channel._get_acl_store().add_to_whitelist(
        "azure_bot", "aad-user-123456"
    )
    before = identity(rt)
    pid = rt.process.health_snapshot()["pid"]
    original = assert_original_archive(rt)
    candidate = formal_source(tmp_path / "invalid-update", "azure_bot")
    manifest = candidate / "plugin.json"
    data = json.loads(manifest.read_text())
    data["version"] = "99.0.0"
    manifest.write_text(json.dumps(data))
    with (candidate / "qwenpaw_channel_azure_bot/driver.py").open(
        "a"
    ) as stream:
        stream.write("\nraise RuntimeError('controlled invalid candidate')\n")
    report = await rt.loader.lifecycle.reload(
        "azure-bot", new_source=candidate
    )
    assert not report.ok and report.errors
    assert await rt.manager.get_channel("azure_bot") is rt.channel
    assert (
        identity(rt) == before and rt.process.health_snapshot()["pid"] == pid
    )
    assert psutil.pid_exists(pid)
    assert assert_original_archive(rt) == original
    await inbound(
        port,
        formal_connector,
        "after-rejected-update",
        "conversation-after-update",
    )
    await eventually(
        lambda: len(formal_connector.requests) == 1 and len(host.calls) == 1
    )
    assert formal_connector.requests[0][1]["text"] == "actual agent answer"
    assert (await rt.manager.stop_one("azure_bot")).stopped
    assert not psutil.pid_exists(pid)
    assert not rt.loader.registry.runtime_owners.leases("azure-bot")
