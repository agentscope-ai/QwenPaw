"""Slack passive loading, admission, lifecycle, update and workspace
isolation."""

import asyncio
import json
import os
import signal
import shutil
from pathlib import Path

import psutil
import pytest

from slack_suite import forbid_host_sdk
from slack_support import (
    callback_done,
    eventually,
    fault_runtime,
    identity,
    push,
    rows,
    runtime,
    set_mode,
    slack,
    slack_sdk,
)
import g2_official_process_suite as common_official

disabled_loader_check = getattr(
    common_official,
    "test_disabled_loader_does_not_spawn_or_import_platform",
)


@pytest.mark.asyncio
async def test_disabled_loader_is_passive(tmp_path, monkeypatch):
    await disabled_loader_check(tmp_path, monkeypatch, "slack")


@pytest.mark.asyncio
async def test_ephemeral_ack_precedes_admission_stable_retry(
    runtime, slack_sdk
):
    from qwenpaw.app.channels.unified_queue_manager import EnqueueResult

    rt = await slack(runtime, slack_sdk, capture_ingress=True)
    attempts, accepted = [], []
    release = asyncio.Event()

    async def admit(payload):
        attempts.append(payload)
        if len(attempts) == 1:
            await release.wait()
        if len(attempts) < 3:
            return EnqueueResult(False, "QUEUE_FULL", True)
        accepted.append(payload)
        return EnqueueResult(True)

    rt.channel.set_enqueue_async(admit)
    push(
        slack_sdk.work,
        callback="slash_commands",
        command="/custom",
        text="data",
    )
    try:
        await eventually(
            lambda: bool(attempts)
            and bool(rows(slack_sdk.work, "platform-ack"))
        )
        assert accepted == []
        assert rows(slack_sdk.work, "platform-ack")[0]["payload"][
            "payload"
        ] == {"response_type": "ephemeral", "text": "Running `/custom`…"}
        release.set()
        await eventually(lambda: len(accepted) == 1)
        assert len(attempts) == 3
        assert all(
            value["meta"]["response_handle"]
            == attempts[0]["meta"]["response_handle"]
            for value in attempts
        )
        assert accepted[0]["acl_sender_id"] == "U456"
        push(
            slack_sdk.work,
            callback="slash_commands",
            command="/custom",
            text="data",
        )
        await callback_done(slack_sdk, 2)
        assert len(accepted) == 1
    finally:
        release.set()


@pytest.mark.asyncio
async def test_exhausted_admission_does_not_poison_platform_dedup(
    runtime, slack_sdk
):
    from qwenpaw.app.channels.unified_queue_manager import EnqueueResult

    rt = await slack(runtime, slack_sdk, capture_ingress=True)
    attempts, accepted = [], []

    async def admit(payload):
        attempts.append(payload)
        if len(attempts) <= 5:
            return EnqueueResult(False, "QUEUE_FULL", True)
        accepted.append(payload)
        return EnqueueResult(True)

    rt.channel.set_enqueue_async(admit)
    push(slack_sdk.work)
    await eventually(lambda: len(attempts) == 5)
    await asyncio.sleep(0.1)
    push(slack_sdk.work)
    await eventually(lambda: len(accepted) == 1)
    assert len(attempts) == 6
    assert all(
        value["meta"]["response_handle"]
        == attempts[0]["meta"]["response_handle"]
        for value in attempts
    )
    assert accepted[0]["session_id"] == "slack:dm:U456"


@pytest.mark.asyncio
async def test_two_workspaces_own_ids_and_workspace_stop(runtime, slack_sdk):
    first = await slack(runtime, slack_sdk)
    second = await slack(
        runtime,
        slack_sdk,
        token="local-B",
        existing_loader=first.loader,
        workspace_name="workspace-B",
    )
    assert identity(first)["instance_id"] != identity(second)["instance_id"]
    assert (
        first.process.health_snapshot()["pid"]
        != second.process.health_snapshot()["pid"]
    )
    for token in ("local-A", "local-B"):
        push(slack_sdk.work, token=token, text="same stable native id")
    await eventually(
        lambda: len(first.ws.requests) == len(second.ws.requests) == 1
    )
    await eventually(
        lambda: bool(rows(slack_sdk.work, "chat.postMessage", token="local-A"))
        and bool(rows(slack_sdk.work, "chat.postMessage", token="local-B"))
    )
    assert (
        first.ws.requests[0].session_id
        == second.ws.requests[0].session_id
        == "slack:dm:U456"
    )
    assert (
        rows(slack_sdk.work, "chat.postMessage", token="local-A")[0]["pid"]
        != rows(slack_sdk.work, "chat.postMessage", token="local-B")[0]["pid"]
    )
    assert (await first.manager.stop_one("slack")).stopped
    push(slack_sdk.work, ident=2, token="local-A", text="late closed instance")
    push(slack_sdk.work, ident=2, token="local-B", text="healthy instance")
    await eventually(lambda: len(second.ws.requests) == 2)
    assert len(first.ws.requests) == 1


@pytest.mark.asyncio
async def test_global_disable_enable_uninstall_preserves_data(
    runtime, slack_sdk
):
    from qwenpaw.config.utils import load_config, save_config

    rt = await slack(runtime, slack_sdk)
    config = load_config()
    config.channels.slack = rt.ws.config.channels.slack
    save_config(config)
    before = load_config().channels.slack.model_dump()
    assets = [
        rt.ws.workspace_dir / name
        for name in (
            "credentials.json",
            "sessions.json",
            "media.bin",
            "business.db",
        )
    ]
    for path in assets:
        path.write_bytes(b"keep:" + path.name.encode())
    pid, stale = rt.process.health_snapshot()["pid"], identity(rt)
    await rt.loader.lifecycle.set_enabled("slack", False)
    assert not psutil.pid_exists(pid)
    assert await rt.manager.get_channel("slack") is None
    await rt.loader.lifecycle.set_enabled("slack", True)
    fresh = await rt.manager.get_channel("slack")
    assert fresh is not None and fresh is not rt.channel
    assert fresh._launch_spec.generation > stale["generation"]
    from qwenpaw.plugins.execution.errors import RpcError

    with pytest.raises(RpcError):
        await fresh.channel_process.call(
            "channel.response.open", {**stale, "to_handle": "C123", "meta": {}}
        )
    fresh_pid = fresh.channel_process.health_snapshot()["pid"]
    report = await rt.loader.unload_plugin("slack", delete_files=True)
    assert report.quiescent and not rt.source.exists()
    assert not psutil.pid_exists(fresh_pid)
    assert "slack" not in load_config().plugins
    assert "slack" in load_config().channel_plugin_state.uninstalled
    assert load_config().channels.slack.model_dump() == before
    assert all(
        path.read_bytes() == b"keep:" + path.name.encode() for path in assets
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("activation_fails", [False, True])
async def test_update_rollback_no_overlap_business_recovers(
    runtime, slack_sdk, tmp_path, activation_fails
):
    rt = await slack(runtime, slack_sdk)
    old_pid, old_version = (
        rt.process.health_snapshot()["pid"],
        rt.record.manifest.version,
    )
    candidate = tmp_path / "candidate"
    shutil.copytree(
        rt.source, candidate, ignore=shutil.ignore_patterns("__pycache__")
    )
    path = candidate / "plugin.json"
    manifest = json.loads(path.read_text())
    manifest["version"] = "99.0.0"
    path.write_text(json.dumps(manifest))
    asset = rt.ws.workspace_dir / "credentials.db"
    asset.write_bytes(b"preserved credential")
    if activation_fails:
        set_mode(slack_sdk.work, "ws-connect-fail-once")
    report = await rt.loader.lifecycle.reload("slack", new_source=candidate)
    assert report.ok is not activation_fails
    assert not psutil.pid_exists(old_pid)
    current = await rt.manager.get_channel("slack")
    assert current is not None
    assert current.channel_process.health_snapshot()["pid"] != old_pid
    assert rt.loader.get_loaded_plugin("slack").manifest.version == (
        old_version if activation_fails else "99.0.0"
    )
    assert asset.read_bytes() == b"preserved credential"
    await current.send("C123", "business restored")
    assert (
        rows(slack_sdk.work, "chat.postMessage")[-1]["arguments"]["text"]
        == "business restored"
    )
    effects = rows(slack_sdk.work)
    connections = [
        index
        for index, row in enumerate(effects)
        if row["kind"] == "ws-connect"
    ]
    assert all(
        any(
            row["kind"] == "http-session-close"
            for row in effects[previous + 1 : current]
        )
        for previous, current in zip(connections, connections[1:])
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("residual", [False, True])
async def test_close_failure_residual_retry_and_no_overlap(
    runtime, slack_sdk, monkeypatch, residual, tmp_path
):
    from qwenpaw.plugins.execution.process_tree import ProcessTree
    from qwenpaw.plugins.registry import PluginRegistry
    from qwenpaw.channel_protocol.errors import RpcError

    rt = await slack(runtime, slack_sdk)
    pid, before = rt.process.health_snapshot()["pid"], identity(rt)
    child_marker = tmp_path / "sdk-retained-child-pid"
    set_mode(
        slack_sdk.work, "ws-close-residual" if residual else "ws-close-unknown"
    )
    try:
        with monkeypatch.context() as boundary:
            if residual:
                original_signal = ProcessTree.signal

                def denied_os_signal(tree, *, force):
                    if tree.pid != pid:
                        original_signal(tree, force=force)

                boundary.setattr(ProcessTree, "signal", denied_os_signal)
            with pytest.raises(RpcError):
                await rt.process.call("shared.stop", before)
            with pytest.raises(RpcError):
                await rt.process.call("shared.stop", before)
            assert len(rows(slack_sdk.work, "ws-close")) == 2
            assert psutil.pid_exists(pid)
            receipt = await rt.manager.stop_one("slack")
            if residual:
                assert (
                    receipt.forced and not receipt.stopped and receipt.residual
                )
                assert await rt.manager.get_channel("slack") is rt.channel
                assert identity(rt) == before
                assert PluginRegistry().runtime_owners.leases("slack")
                with pytest.raises(
                    RuntimeError, match="not stopped|STOPPING|OWNED"
                ):
                    await rt.manager.start_one("slack", rt.ws.config)
            else:
                assert (
                    receipt.stopped and receipt.exited and not receipt.residual
                )
                assert not psutil.pid_exists(pid)
        set_mode(slack_sdk.work, "")
        if residual:
            retry = await rt.manager.stop_one("slack")
            assert retry.stopped and retry.exited and not retry.residual
        fresh = await rt.manager.start_one("slack", rt.ws.config)
        assert fresh.channel.channel_process.health_snapshot()["pid"] != pid
        assert fresh.channel._launch_spec.generation > before["generation"]
    finally:
        set_mode(slack_sdk.work, "")
        if child_marker.exists():
            child_pid = int(child_marker.read_text())
            if psutil.pid_exists(child_pid):
                os.kill(child_pid, signal.SIGKILL)
