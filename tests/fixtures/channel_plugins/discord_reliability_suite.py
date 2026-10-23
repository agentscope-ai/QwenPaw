"""Discord admission, offline restoration and installed lifecycle contracts."""

import asyncio
import hashlib
import json
from pathlib import Path
import time
import shutil

import psutil
import pytest

from discord_suite import forbid_host_sdk
from discord_support import (
    callback_done,
    discord,
    discord_sdk,
    eventually,
    fault_runtime,
    finish,
    identity,
    push,
    route,
    rows,
    runtime,
    send,
    set_mode,
)
from discord_stream_suite import stream
from extension_sample import ROOT
from g2_lifecycle_suite import official_zip_source
from g2_official_process_suite import (
    test_disabled_loader_does_not_spawn_or_import_platform as disabled_loader_check,
)


@pytest.mark.asyncio
async def test_disabled_loader_is_passive(tmp_path, monkeypatch):
    await disabled_loader_check(tmp_path, monkeypatch, "discord")


@pytest.mark.asyncio
async def test_exhausted_host_admission_does_not_cache_native_message_id(
    runtime, discord_sdk
):
    from qwenpaw.app.channels.unified_queue_manager import EnqueueResult

    rt = await discord(runtime, discord_sdk, capture_ingress=True)
    attempts, accepted = [], []

    async def admit(payload):
        attempts.append(payload)
        if len(attempts) <= 5:
            return EnqueueResult(False, "QUEUE_FULL", True)
        accepted.append(payload)
        return EnqueueResult(True)

    rt.channel.set_enqueue_async(admit)
    push(discord_sdk.work, ident=1)
    await callback_done(discord_sdk)
    assert len(attempts) == 5 and accepted == []
    assert all(
        row["meta"]["response_handle"]
        == attempts[0]["meta"]["response_handle"]
        for row in attempts
    )
    push(discord_sdk.work, ident=1)
    await eventually(lambda: len(accepted) == 1)
    assert len(attempts) == 6
    assert accepted[0]["acl_sender_id"] == "42"


@pytest.mark.asyncio
async def test_restore_pending_stream_waits_for_connected_before_final_edit(
    runtime, discord_sdk
):
    from qwenpaw.plugins.execution.errors import RpcError

    rt = await discord(runtime, discord_sdk, streaming_enabled=True)
    handle = await route(rt)
    await stream(rt, handle, "start", delivery_id="start", text="partial")
    set_mode(discord_sdk.work, "edit-reject")
    with pytest.raises(RpcError):
        await finish(rt, handle)
    assert len(rows(discord_sdk.work, "edit")) == 1
    await rt.loader.lifecycle.set_enabled("discord", False)
    set_mode(discord_sdk.work, "gateway-block")
    enabling = asyncio.create_task(
        rt.loader.lifecycle.set_enabled("discord", True)
    )
    try:
        await eventually(lambda: len(rows(discord_sdk.work, "gateway")) == 2)
        assert len(rows(discord_sdk.work, "edit")) == 1
        set_mode(discord_sdk.work, "")
        await enabling
        await eventually(lambda: len(rows(discord_sdk.work, "edit")) == 2)
        assert rows(discord_sdk.work, "edit")[-1]["content"] == "partial"
    finally:
        set_mode(discord_sdk.work, "")
        await asyncio.gather(enabling, return_exceptions=True)


@pytest.mark.asyncio
async def test_actual_official_zip_roundtrip_records_parent_and_all_workers(
    runtime, discord_sdk, tmp_path
):
    started = time.perf_counter()
    rt = await runtime(
        "discord",
        source_factory=official_zip_source,
        bot_token="local-A",
        python_executable=discord_sdk.python,
        runtime_identity=discord_sdk.identity,
        dependency_paths=(discord_sdk.site,),
    )
    push(discord_sdk.work, text="archive ingress")
    await eventually(
        lambda: len(rt.ws.requests) == 1
        and bool(rows(discord_sdk.work, "send"))
    )
    assert rt.source.is_relative_to(rt.loader.plugin_dirs[0])
    assert rt.source != ROOT / "plugins/channel/discord"
    assert rows(discord_sdk.work, "send")[0]["content"] == "host answer"
    parent, child = psutil.Process(), psutil.Process(
        rt.process.health_snapshot()["pid"]
    )
    bundle = tmp_path / "official-bundle"
    artifact = next(bundle.rglob("*discord*.zip"))
    data = {
        "scope": "Discord actual official ZIP + SDK boundary simulation; not all 16 artifact target",
        "parent_pid": parent.pid,
        "parent_rss_bytes": parent.memory_info().rss,
        "parent_threads": parent.num_threads(),
        "workers": [
            {
                "pid": child.pid,
                "rss_bytes": child.memory_info().rss,
                "threads": child.num_threads(),
            }
        ],
        "install_connect_business_ms": (time.perf_counter() - started) * 1000,
        "artifact_bytes": artifact.stat().st_size,
        "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
    }
    data["parent_plus_workers_rss_bytes"] = data["parent_rss_bytes"] + sum(
        row["rss_bytes"] for row in data["workers"]
    )
    assert data["parent_plus_workers_rss_bytes"] > data["parent_rss_bytes"]


@pytest.mark.asyncio
async def test_disable_enable_and_uninstall_preserve_channel_and_business_files(
    runtime, discord_sdk
):
    from qwenpaw.config.utils import load_config, save_config

    rt = await discord(runtime, discord_sdk)
    config = load_config()
    config.channels.discord = rt.ws.config.channels.discord
    save_config(config)
    before = load_config().channels.discord.model_dump()
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
    pid = rt.process.health_snapshot()["pid"]
    await rt.loader.lifecycle.set_enabled("discord", False)
    assert not psutil.pid_exists(pid)
    assert await rt.manager.get_channel("discord") is None
    await rt.loader.lifecycle.set_enabled("discord", True)
    fresh = await rt.manager.get_channel("discord")
    assert fresh is not None and fresh is not rt.channel
    fresh_pid = fresh.channel_process.health_snapshot()["pid"]
    assert fresh_pid != pid
    report = await rt.loader.unload_plugin("discord", delete_files=True)
    assert report.quiescent and not rt.source.exists()
    assert not psutil.pid_exists(fresh_pid)
    assert "discord" not in load_config().plugins
    assert "discord" in load_config().channel_plugin_state.uninstalled
    assert load_config().channels.discord.model_dump() == before
    assert all(
        path.read_bytes() == b"keep:" + path.name.encode() for path in assets
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("activation_fails", [False, True])
async def test_update_and_activation_rollback_restore_business_without_overlap(
    runtime, discord_sdk, tmp_path, activation_fails
):
    rt = await discord(runtime, discord_sdk)
    old_pid = rt.process.health_snapshot()["pid"]
    old_version = rt.record.manifest.version
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
        set_mode(discord_sdk.work, "gateway-fail-once")
    report = await rt.loader.lifecycle.reload("discord", new_source=candidate)
    assert report.ok is not activation_fails
    assert not psutil.pid_exists(old_pid)
    current = await rt.manager.get_channel("discord")
    assert current is not None
    assert current.channel_process.health_snapshot()["pid"] != old_pid
    assert rt.loader.get_loaded_plugin("discord").manifest.version == (
        old_version if activation_fails else "99.0.0"
    )
    assert asset.read_bytes() == b"preserved credential"
    await current.send("discord:ch:123", "business restored")
    assert rows(discord_sdk.work, "send")[-1]["content"] == "business restored"
    effects = rows(discord_sdk.work)
    gateways = [
        index for index, row in enumerate(effects) if row["kind"] == "gateway"
    ]
    assert all(
        any(
            row["kind"] == "gateway-close"
            for row in effects[previous + 1 : current]
        )
        for previous, current in zip(gateways, gateways[1:])
    )
