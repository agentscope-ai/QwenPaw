# -*- coding: utf-8 -*-
"""Local Whisper uses production framework install, discovery and uninstall."""

# pylint: disable=protected-access,redefined-outer-name

import asyncio
import builtins
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.config.utils import load_config, mutate_config
from qwenpaw.plugins import local_transcription as local
from qwenpaw.plugins.dependency_gate import GateDecision
from qwenpaw.plugins.lifecycle import UnloadMode
from qwenpaw.plugins.loader import PluginLoader
from qwenpaw.plugins.testing import PluginTestHost


@pytest.fixture
async def setup(tmp_path, monkeypatch):
    async with PluginTestHost(tmp_path / "host") as host:
        gate = AsyncMock(return_value=GateDecision(False, True))
        monkeypatch.setattr(
            host._loader,
            "_ensure_dependencies_installed",
            gate,
        )
        monkeypatch.setattr(
            local,
            "dependency_status",
            lambda: {
                "available": True,
                "whisper_installed": True,
                "ffmpeg_installed": True,
            },
        )
        service = local.LocalTranscriptionService(
            host._loader,
            host.root / "plugin_runtime" / "migrations" / "local-whisper.json",
        )
        try:
            yield host, service, gate
        finally:
            await service.close()


def select(provider="local_whisper"):
    mutate_config(
        lambda saved: setattr(
            saved.agents,
            "transcription_provider_type",
            provider,
        ),
    )


async def uninstall(loader):
    from qwenpaw.app.routers.plugins import uninstall_plugin_source

    await uninstall_plugin_source(
        local.PLUGIN_ID,
        app=SimpleNamespace(state=SimpleNamespace(plugin_loader=loader)),
    )


async def install(service):
    service.request()
    await service.task
    assert not service.error


@pytest.mark.parametrize("restart", [False, True])
async def test_uninstall_stays_missing_with_dependencies_present(
    setup,
    restart,
):
    """Regression: dependencies survive, but the plugin must not resurrect."""
    host, service, _ = setup
    select()
    await service.start()
    await service.task
    assert local.get_status()["available"] is True
    await uninstall(host._loader)
    if restart:
        await service.close()
        await service.start()
    assert (
        host._loader.registry.get_transcription_backend("local_whisper")
        is None
    )
    status = local.get_status()
    assert status["available"] is False
    assert status["plugin_installed"] is False
    assert status["state"] == "missing"
    assert status["whisper_installed"] is True
    await install(service)
    assert local.get_status()["available"] is True


async def test_choice_never_installs_or_enables_plugin(setup):
    from qwenpaw.app.routers.workspace import put_transcription_provider_type

    host, service, gate = setup
    await service.start()
    await put_transcription_provider_type(
        {"transcription_provider_type": "local_whisper"},
    )
    assert service.task is None
    gate.assert_not_called()
    assert local.PLUGIN_ID not in load_config().plugins
    await service.close()
    await service.start()
    assert service.task is None
    await install(service)
    await host._loader.lifecycle.set_enabled(local.PLUGIN_ID, False)
    await put_transcription_provider_type(
        {"transcription_provider_type": "local_whisper"},
    )
    assert local.get_status()["state"] == "disabled"
    await host._loader.lifecycle.set_enabled(local.PLUGIN_ID, True)
    assert local.get_status()["available"] is True


async def test_framework_discovers_install_after_restart(setup, monkeypatch):
    host, service, gate = setup
    await service.start()
    await install(service)
    path = host.root / "plugins" / local.PLUGIN_ID
    assert host._loader.find_installed_plugin_dir(local.PLUGIN_ID) == path
    assert host._loader.get_loaded_plugin(local.PLUGIN_ID).source_path == path
    await service.close()
    await host._loader.lifecycle.unload(local.PLUGIN_ID, UnloadMode.UNLOAD)
    # Clear process-local registrations before exercising a fresh loader.
    restarted = PluginLoader([host.root / "plugins"])
    monkeypatch.setattr(restarted, "_ensure_dependencies_installed", gate)
    service.loader = restarted
    try:
        gate.reset_mock()
        await restarted.load_all_plugins(configs=load_config().plugins)
        await restarted.activate_all_loaded()
        await service.start()
        assert local.get_status()["available"] is True
        assert all(not c.kwargs["allow_install"] for c in gate.call_args_list)
        await uninstall(restarted)
    finally:
        if restarted.get_loaded_plugin(local.PLUGIN_ID):
            await restarted.lifecycle.unload(
                local.PLUGIN_ID,
                UnloadMode.UNLOAD,
            )


async def test_install_then_concurrent_uninstall_cannot_reactivate(setup):
    host, service, gate = setup
    await service.start()
    started, finish = asyncio.Event(), asyncio.Event()

    async def prepare(*_args, **_kwargs):
        started.set()
        await finish.wait()
        return GateDecision(False, True)

    gate.side_effect = prepare
    service.request()
    await asyncio.wait_for(started.wait(), 3)
    first_task = service.task
    for _ in range(4):
        service.request()
    assert service.task is first_task
    pending = asyncio.create_task(uninstall(host._loader))
    try:
        await asyncio.sleep(0)
        assert not pending.done()
        select("whisper_api")
        finish.set()
        await asyncio.wait_for(asyncio.gather(first_task, pending), 5)
        assert (
            load_config().agents.transcription_provider_type == "whisper_api"
        )
        assert local.get_status()["state"] == "missing"
        assert not host._loader.registry.get_transcription_backend(
            "local_whisper",
        )
    finally:
        finish.set()
        await pending


async def test_failed_migration_requires_explicit_retry(setup):
    _, service, gate = setup
    select()
    gate.side_effect = RuntimeError("offline")
    await service.start()
    await service.task
    assert "offline" in local.get_status()["error"]
    assert load_config().agents.transcription_provider_type == "local_whisper"
    calls = gate.call_count
    await service.close()
    await service.start()
    assert gate.call_count == calls
    gate.side_effect = None
    await install(service)
    assert local.get_status()["available"] is True


async def test_missing_ffmpeg_does_not_hide_installed_plugin(
    setup,
    monkeypatch,
):
    _, service, _ = setup
    await service.start()
    await install(service)
    monkeypatch.setattr(
        local,
        "dependency_status",
        lambda: {
            "available": False,
            "whisper_installed": True,
            "ffmpeg_installed": False,
        },
    )
    status = local.get_status()
    assert status["plugin_installed"] is True
    assert status["plugin_status"] == "active"
    assert status["state"] == "missing_dependencies"
    assert status["available"] is False


async def test_status_never_imports_whisper_or_torch(setup, monkeypatch):
    _, service, _ = setup
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        assert name.split(".")[0] not in {"whisper", "torch"}
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    await service.start()
    await install(service)
    assert local.get_status()["available"] is True


async def test_uninstall_waits_for_real_transcription_worker(
    setup,
    monkeypatch,
):
    """The real SDK invocation must keep a running recognizer owned."""
    import sys
    import threading

    from qwenpaw.plugins.activity import PluginBusyError

    host, service, _ = setup
    entered, release = threading.Event(), threading.Event()

    def recognize(_path):
        entered.set()
        assert release.wait(5)
        return {"text": "test"}

    monkeypatch.setitem(
        sys.modules,
        "whisper",
        SimpleNamespace(
            load_model=lambda _: SimpleNamespace(transcribe=recognize),
        ),
    )
    monkeypatch.setattr("shutil.which", lambda _: "/test/ffmpeg")
    await service.start()
    await install(service)
    task = asyncio.create_task(host.transcribe("local_whisper", "/audio.wav"))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        with pytest.raises(PluginBusyError):
            await uninstall(host._loader)
        assert host._loader.find_installed_plugin_dir(local.PLUGIN_ID)
        assert not task.done()
    finally:
        release.set()
        result = await task
    assert result.text == "test"
    await uninstall(host._loader)
    assert local.get_status()["state"] == "missing"


async def test_invalid_migration_marker_never_reinstalls(setup):
    _, service, gate = setup
    select()
    service.state_path.parent.mkdir(parents=True, exist_ok=True)
    service.state_path.write_text("broken-json")
    await service.start()
    assert service.task is None
    gate.assert_not_called()
    assert local.get_status()["state"] == "missing"


async def test_existing_framework_install_never_repairs_on_boot(setup):
    host, service, gate = setup
    # CLI or another framework entry can install before the voice page starts.
    await host._loader.load_plugin_from_path(local.SOURCE)
    select()
    gate.reset_mock()
    assert not service.state_path.exists()
    await service.start()
    assert service.task is None
    gate.assert_not_called()
    assert local.get_status()["available"] is True
