# -*- coding: utf-8 -*-
"""Local Whisper uses production framework install, discovery and uninstall."""

# pylint: disable=protected-access,redefined-outer-name

import asyncio
import builtins
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.config.utils import load_config, mutate_config
from qwenpaw.plugins import local_whisper as local
from qwenpaw.plugins.dependency_gate import GateDecision
from qwenpaw.plugins.lifecycle import UnloadMode
from qwenpaw.plugins.loader import PluginLoader
from qwenpaw.plugins.testing import PluginTestHost


@pytest.fixture
async def setup(tmp_path, monkeypatch, whisper_dependency_inventory):
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
        service = local.LocalWhisperInstallService(
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
    assert (await local.get_runtime_status())["state"] == "missing"
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
    assert (await local.get_runtime_status())["state"] == "disabled"
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


async def test_status_never_imports_whisper_or_torch(
    tmp_path,
    monkeypatch,
    whisper_dependency_inventory,
):
    monkeypatch.syspath_prepend(str(whisper_dependency_inventory))
    monkeypatch.setenv("PIP_NO_INDEX", "1")
    monkeypatch.setattr("shutil.which", lambda _: "/test/ffmpeg")
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        assert name.split(".")[0] not in {"whisper", "torch"}
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    async with PluginTestHost(tmp_path / "host") as host:
        service = local.LocalWhisperInstallService(
            host._loader,
            host.root / "migration.json",
        )
        try:
            await service.start()
            await install(service)
            assert local.get_status()["available"] is True
            assert (await local.get_runtime_status())["available"] is True
            assert (await host.transcription_status("local_whisper")).available
        finally:
            await service.close()


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
        # Reading status must not wait for inference to release the model lock.
        status = await asyncio.wait_for(local.get_runtime_status(), 1)
        assert status["available"] is True
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


@pytest.mark.parametrize("repair", [False, True])
async def test_dependency_confirmation_survives_restart(
    setup,
    monkeypatch,
    repair,
):
    from qwenpaw.plugins import dependency_upgrade as upgrades

    host, service, gate = setup
    await service.start()
    if repair:
        await install(service)
    operation = {
        "id": "pending-whisper-upgrade",
        "plugin_id": local.PLUGIN_ID,
        "status": "needs_confirmation",
        "message": "Confirm dependency changes",
        "changes": [
            {"name": "torch", "current_version": "1", "target_version": "2"},
        ],
    }
    manager = upgrades.dependency_upgrades(host._loader)

    def lookup(operation_id):
        assert operation_id == operation["id"]
        return dict(operation)

    monkeypatch.setattr(manager, "status", lookup)
    stage = AsyncMock(return_value=operation)
    monkeypatch.setattr(manager, "stage", stage)
    gate.side_effect = RuntimeError("DEPENDENCY_RESTART_REQUIRED")
    await install(service)
    status = local.get_status()
    assert status["state"] == "needs_confirmation"
    assert status["dependency_upgrade"] == operation
    stage.assert_awaited_once()
    calls = gate.call_count
    await service.close()
    restarted = local.LocalWhisperInstallService(
        host._loader,
        service.state_path,
    )
    try:
        await restarted.start()
        assert local.get_status()["dependency_upgrade"] == operation
        await install(restarted)
        assert gate.call_count == calls
        operation["status"] = "cancelled"
        assert local.get_status().get("dependency_upgrade") is None
        gate.side_effect = None
        await install(restarted)
        assert gate.call_count > calls
        assert local.get_status()["available"] is True
    finally:
        await restarted.close()


@pytest.mark.parametrize("cancel_close", [False, True])
async def test_close_waits_for_cleanup_and_preserves_caller_cancellation(
    tmp_path,
    cancel_close,
):
    from qwenpaw.utils.io_utils import run_async_to_completion

    started, cleaning, release = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )

    async def install_job():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await run_async_to_completion(release.wait())

    service = local.LocalWhisperInstallService(
        None,
        tmp_path / "migration.json",
    )
    service.task = asyncio.create_task(install_job())
    await started.wait()
    closing = asyncio.create_task(service.close())
    try:
        await asyncio.wait_for(cleaning.wait(), 1)
        if cancel_close:
            closing.cancel()
            await asyncio.sleep(0)
        assert not closing.done()
        release.set()
        if cancel_close:
            with pytest.raises(asyncio.CancelledError):
                await closing
        else:
            await closing
        assert service.task.cancelled()
    finally:
        release.set()
        await asyncio.gather(closing, service.task, return_exceptions=True)


async def test_import_failure_and_metadata_less_dependency_recover_through_http(
    tmp_path,
    monkeypatch,
    whisper_dependency_inventory,
):
    import shutil
    import sys
    import httpx
    from fastapi import FastAPI
    from qwenpaw.app.routers.workspace import router

    site = whisper_dependency_inventory
    (site / "torch.py").write_text("READY = True\n")
    (site / "whisper.py").write_text(
        "import torch\nfrom types import SimpleNamespace\n"
        "def load_model(name):\n"
        "    return SimpleNamespace(transcribe=lambda path: {'text': 'hello'})\n",
    )
    shutil.rmtree(site / "torch-2.0.dist-info")
    monkeypatch.syspath_prepend(str(site))
    monkeypatch.delitem(sys.modules, "torch", raising=False)
    monkeypatch.delitem(sys.modules, "whisper", raising=False)
    monkeypatch.setattr("shutil.which", lambda _: "/test/ffmpeg")
    # Avoid publishing these small test modules into the surrounding process.
    with monkeypatch.context() as modules:
        modules.setitem(sys.modules, "torch", None)
        modules.delitem(sys.modules, "torch")
        modules.setitem(sys.modules, "whisper", None)
        async with PluginTestHost(tmp_path / "host") as host:
            select()
            await host.load(local.SOURCE)
            service = local.LocalWhisperInstallService(
                host._loader,
                host.root / "migration.json",
            )
            service.state_path.write_text("{}")
            await service.start()
            app = FastAPI()
            app.include_router(router, prefix="/api")
            try:
                result = await host.transcribe("local_whisper", "/audio.wav")
                assert result.error == "unavailable"
                # Runtime failure leaves installation and retry admission intact.
                assert local.get_status()["state"] == "ready"
                status = await local.get_runtime_status()
                assert status["available"] is False
                assert status["state"] == "ready"
                assert "whisper" in status["error"]
                assert status["plugin_status"] == "active"
                modules.delitem(sys.modules, "whisper")
                # Reading status must not retry the repaired import.
                assert not (await local.get_runtime_status())["available"]
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    response = await client.post(
                        "/api/workspace/transcribe",
                        files={
                            "file": ("audio.wav", b"RIFF mock", "audio/wav"),
                        },
                    )
                assert response.status_code == 200, response.text
                assert response.json() == {"text": "hello"}
                assert local.get_status()["available"] is True
                status = await local.get_runtime_status()
                assert status["available"] is True
                assert status["error"] == local.get_status()["error"]
            finally:
                await service.close()


@pytest.mark.parametrize("text,expected", [("  hello  ", "hello"), ("  ", "")])
async def test_optional_plugin_model_cache_and_empty_result(
    tmp_path,
    monkeypatch,
    text,
    expected,
    whisper_dependency_inventory,
):
    import sys
    from unittest.mock import MagicMock
    from qwenpaw.plugins.transcription import TranscriptionResult

    optional_source = local.SOURCE
    from qwenpaw.plugins.dependency_gate import GateDecision

    monkeypatch.setattr(
        "qwenpaw.plugins.loader.PluginLoader._ensure_dependencies_installed",
        AsyncMock(return_value=GateDecision(False, True)),
    )

    model = MagicMock()
    model.transcribe.return_value = {"text": text}
    whisper = SimpleNamespace(load_model=MagicMock(return_value=model))
    monkeypatch.setitem(sys.modules, "whisper", whisper)
    monkeypatch.setattr("shutil.which", lambda name: "/test/ffmpeg")
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(optional_source)
        whisper.load_model.assert_not_called()
        for _ in range(2):
            result = await host.transcribe("local_whisper", "/audio.wav")
            assert result == TranscriptionResult(
                expected,
                "" if expected else "empty",
            )
        whisper.load_model.assert_called_once_with("base")
        assert (await host.unload("local-whisper")).quiescent
        await host.load(optional_source)
        await host.transcribe("local_whisper", "/audio.wav")
        assert whisper.load_model.call_count == 2


async def test_import_recovery_clears_error_before_model_or_audio_failure(
    setup,
    monkeypatch,
):
    from unittest.mock import MagicMock

    host, service, _ = setup
    await service.start()
    await install(service)
    monkeypatch.setattr("shutil.which", lambda _: "/test/ffmpeg")
    original = builtins.__import__
    broken = True
    model = MagicMock()
    model.transcribe.side_effect = [
        ValueError("invalid audio"),
        {"text": ""},
        {"text": "hello"},
    ]
    whisper = SimpleNamespace(
        load_model=MagicMock(
            side_effect=[RuntimeError("download failed"), model],
        ),
    )

    def import_module(name, *args, **kwargs):
        if name == "whisper":
            if broken:
                raise OSError("dependency import failed")
            return whisper
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_module)
    result = await host.transcribe("local_whisper", "/audio.wav")
    assert result.error == "unavailable"
    status = await local.get_runtime_status()
    assert status["available"] is False
    assert status["error"] == "dependency import failed"
    broken = False
    assert not (await local.get_runtime_status())["available"]
    for expected in ("failed", "failed", "empty", ""):
        result = await host.transcribe("local_whisper", "/audio.wav")
        assert result.error == expected
        status = await local.get_runtime_status()
        assert status["available"] is True
        assert status["error"] == ""
    assert whisper.load_model.call_count == 2


@pytest.mark.parametrize("old_result", ["cancelled", "failed", "read_error"])
async def test_late_upgrade_query_cannot_replace_new_confirmation(
    tmp_path,
    monkeypatch,
    old_result,
):
    import json
    import threading
    from contextlib import asynccontextmanager
    from qwenpaw.plugins.dependency_upgrade import DependencyUpgradeRequired

    entered, release = threading.Event(), threading.Event()
    first = True
    operation = {
        "id": "new-upgrade",
        "status": "needs_confirmation",
        "message": "Confirm new upgrade",
    }

    def lookup(operation_id):
        nonlocal first
        if operation_id == operation["id"]:
            return dict(operation)
        assert operation_id == "old-upgrade"
        if first:
            first = False
            entered.set()
            assert release.wait(5)
            if old_result == "read_error":
                raise OSError("old operation read failed")
        return {
            "status": "failed" if old_result == "failed" else "cancelled",
            "error": {"message": "old operation failed"},
        }

    @asynccontextmanager
    async def lifecycle(_plugin_id):
        yield

    async def require_upgrade(*_args, **_kwargs):
        raise DependencyUpgradeRequired(operation)

    monkeypatch.setattr(
        local,
        "dependency_upgrades",
        lambda _: SimpleNamespace(status=lookup),
    )
    monkeypatch.setattr(local, "install_with_upgrade", require_upgrade)
    service = local.LocalWhisperInstallService(
        SimpleNamespace(
            plugin_lifecycle=lifecycle,
            find_installed_plugin_dir=lambda _: None,
        ),
        tmp_path / "migration.json",
    )
    service.state_path.write_text("{}")
    service.operation_id = "old-upgrade"
    pending = asyncio.create_task(asyncio.to_thread(service.pending_upgrade))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        await service._install()
        assert service.operation_id == operation["id"]
        release.set()
        await pending
        assert service.operation_id == operation["id"]
        assert service.error == ""
        assert service.pending_upgrade() == operation
        assert json.loads(service.state_path.read_text()) == {
            "dependency_operation_id": operation["id"],
        }
    finally:
        release.set()
        await pending
