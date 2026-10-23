"""Production plugin transactions, passive discovery and retained user data."""

import json
import shutil

import psutil
import pytest

from extension_sample import ROOT
from telegram_business_suite import forbid_host_sdk
from telegram_support import (
    eventually,
    fault_runtime,
    identity,
    rows,
    runtime,
    set_mode,
    telegram,
    telegram_sdk,
)
import g2_official_process_suite as common_official

disabled_loader_check = getattr(
    common_official, "test_disabled_loader_does_not_spawn_or_import_platform"
)


@pytest.mark.asyncio
async def test_globally_disabled_discovery_is_passive_without_sdk_or_pid(
    tmp_path, monkeypatch
):
    await disabled_loader_check(tmp_path, monkeypatch, "telegram")


@pytest.mark.asyncio
async def test_global_disable_enable_stale_generation_uninstall_keep_data(
    runtime, telegram_sdk
):
    from qwenpaw.config.utils import load_config, save_config
    from qwenpaw.plugins.execution.errors import RpcError

    rt = await telegram(runtime, telegram_sdk)
    config = load_config()
    config.channels.telegram = rt.ws.config.channels.telegram
    save_config(config)
    before = load_config().channels.telegram.model_dump()
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
    await rt.loader.lifecycle.set_enabled("telegram", False)
    assert not psutil.pid_exists(pid)
    assert await rt.manager.get_channel("telegram") is None
    await rt.loader.lifecycle.set_enabled("telegram", True)
    fresh = await rt.manager.get_channel("telegram")
    assert fresh is not None and fresh is not rt.channel
    assert fresh._launch_spec.generation > stale["generation"]
    with pytest.raises(RpcError):
        await fresh.channel_process.call(
            "channel.response.open",
            {**stale, "to_handle": "12345", "meta": {}},
        )
    fresh_pid = fresh.channel_process.health_snapshot()["pid"]
    report = await rt.loader.unload_plugin("telegram", delete_files=True)
    assert report.quiescent and not rt.source.exists()
    assert not psutil.pid_exists(fresh_pid)
    assert "telegram" not in load_config().plugins
    assert "telegram" in load_config().channel_plugin_state.uninstalled
    assert load_config().channels.telegram.model_dump() == before
    assert all(
        path.read_bytes() == b"keep:" + path.name.encode() for path in assets
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("activation_fails", [False, True])
async def test_update_and_rollback_require_old_close_before_new_connection(
    runtime, telegram_sdk, tmp_path, activation_fails
):
    rt = await telegram(runtime, telegram_sdk)
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
        set_mode(telegram_sdk.work, "getMe-token-once")
    report = await rt.loader.lifecycle.reload("telegram", new_source=candidate)
    assert report.ok is not activation_fails
    assert not psutil.pid_exists(old_pid)
    current = await rt.manager.get_channel("telegram")
    assert current is not None
    assert current.channel_process.health_snapshot()["pid"] != old_pid
    assert rt.loader.get_loaded_plugin("telegram").manifest.version == (
        old_version if activation_fails else "99.0.0"
    )
    assert asset.read_bytes() == b"preserved credential"
    await current.send("12345", "business restored")
    assert (
        rows(telegram_sdk.work, "sendMessage")[-1]["arguments"]["text"]
        == "business restored"
    )
    effects = rows(telegram_sdk.work)
    starts = [i for i, value in enumerate(effects) if value["kind"] == "getMe"]
    assert all(
        any(
            value["kind"] == "http-close-exit"
            for value in effects[left + 1 : right]
        )
        for left, right in zip(starts, starts[1:])
    )


@pytest.mark.asyncio
async def test_enabled_empty_token_never_connects_or_keeps_a_worker(
    runtime, telegram_sdk
):
    from g2_official_process_suite import official_source

    with pytest.raises(
        RuntimeError, match="Projection channel failed: CHANNEL_NOT_CONNECTED"
    ):
        await runtime(
            "telegram",
            source_factory=official_source,
            bot_token="",
            python_executable=telegram_sdk.python,
            runtime_identity=telegram_sdk.identity,
            dependency_paths=(telegram_sdk.site,),
        )
    ws = runtime.workspaces[-1]
    assert ws.config.channels.telegram.enabled is True
    assert ws.config.channels.telegram.bot_token == ""
    channel = await ws.channel_manager.get_channel("telegram")
    assert (
        channel is None
        or channel.channel_process.health_snapshot()["pid"] is None
    )
    assert rows(telegram_sdk.work) == []
    await ws.channel_manager.stop_all()
    await ws.channel_manager.stop_all()
