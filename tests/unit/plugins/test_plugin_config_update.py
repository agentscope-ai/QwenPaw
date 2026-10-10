# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Config rebuild and enabled flag."""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.plugins.architecture import PluginManifest
from qwenpaw.plugins.lifecycle import PluginState, UnloadMode
from qwenpaw.plugins.loader import PluginLoader
from qwenpaw.plugins.settings import (
    is_plugin_enabled,
    persist_plugin_settings,
    runtime_config,
)
from qwenpaw.plugins.workspace_projector import WorkspaceProjector
from qwenpaw.runtime.slash_command_registry import SlashCommandRegistry


def _write_plugin(
    root: Path,
    plugin_id: str,
    *,
    body: str = "pass",
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "id": plugin_id,
                "version": "1.0.0",
                "name": plugin_id,
                "entry": {"backend": "main.py"},
            },
        ),
        encoding="utf-8",
    )
    (root / "main.py").write_text(
        "class _P:\n"
        f"    def register(self, api):\n"
        f"        {body}\n"
        "plugin = _P()\n",
        encoding="utf-8",
    )
    return root


def _slash_workspace():
    return SimpleNamespace(
        agent_id="talk",
        plugins=SimpleNamespace(
            slash_command_registry=SlashCommandRegistry(),
        ),
    )


async def _load_with_workspace(
    tmp_path: Path,
    fresh_registry,
    plugin_id: str,
    body: str,
    config: dict | None = None,
):
    workspace = _slash_workspace()
    fresh_registry.projector = WorkspaceProjector(
        live_workspaces=lambda: [workspace],
    )
    fresh_registry.set_workspace_manager(
        SimpleNamespace(agents={"talk": workspace}),
    )
    installed = _write_plugin(
        tmp_path / "plugins" / plugin_id,
        plugin_id,
        body=body,
    )
    loader = PluginLoader(plugin_dirs=[tmp_path / "plugins"])
    loader.registry = fresh_registry
    manifest = PluginManifest.from_dict(
        json.loads((installed / "plugin.json").read_text(encoding="utf-8")),
    )
    await loader.load_plugin(manifest, installed, config)
    await loader.run_plugin_startup_hooks(plugin_id)
    return loader, workspace


def test_runtime_config_strips_enabled():
    assert runtime_config({"enabled": False, "token": "x"}) == {"token": "x"}
    assert is_plugin_enabled(None) is True
    assert is_plugin_enabled({"enabled": False}) is False


@pytest.mark.asyncio
async def test_update_config_success_replaces_slash(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr(
        "qwenpaw.constant.WORKING_DIR",
        tmp_path / "work",
    )
    monkeypatch.setattr(
        "qwenpaw.plugins.settings.persist_plugin_settings",
        lambda *args, **kwargs: None,
    )
    body = (
        "name = api.config.get('cmd', 'old')\n"
        "        api.register_slash_command(name, lambda c, a: None)"
    )
    loader, workspace = await _load_with_workspace(
        tmp_path,
        fresh_registry,
        "cfg",
        body,
        {"cmd": "old"},
    )
    names = workspace.plugins.slash_command_registry.names()
    assert "old" in names
    report = await loader.lifecycle.update_config("cfg", {"cmd": "new"})
    assert report.ok
    names = workspace.plugins.slash_command_registry.names()
    assert "new" in names
    assert "old" not in names


@pytest.mark.asyncio
@pytest.mark.parametrize("restore_fails", [False, True])
async def test_config_write_failure_restores_runtime_and_allows_retry(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
    restore_fails,
):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(
        "qwenpaw.constant.WORKING_DIR",
        tmp_path / "work",
    )
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_config_path",
        lambda: config_path,
    )
    persist_plugin_settings("cfg", config={"cmd": "old"})
    before = config_path.read_bytes()
    loader, workspace = await _load_with_workspace(
        tmp_path,
        fresh_registry,
        "cfg",
        "api.register_slash_command(api.config['cmd'], lambda c, a: None)",
        {"cmd": "old"},
    )

    def fail_save(*_args, **_kwargs):
        raise OSError("disk write failed")

    monkeypatch.setattr(
        "qwenpaw.plugins.settings.persist_plugin_settings",
        fail_save,
    )
    if restore_fails:
        reregister = loader.reregister_unlocked

        async def fail_restore(plugin_id, config):
            if config == {"cmd": "old"}:
                raise RuntimeError("old config restore failed")
            await reregister(plugin_id, config)

        monkeypatch.setattr(loader, "reregister_unlocked", fail_restore)
    report = await loader.lifecycle.update_config("cfg", {"cmd": "new"})
    assert not report.ok
    assert "disk write failed" in report.errors
    assert config_path.read_bytes() == before
    if restore_fails:
        assert report.needs_restart
        assert "restore failed: old config restore failed" in report.errors
        assert loader.lifecycle.get_instance("cfg").state is PluginState.FAILED
        assert loader.get_loaded_plugin("cfg").status == "failed"
        assert not workspace.plugins.slash_command_registry.names()
        return
    assert not report.needs_restart
    assert loader.lifecycle.get_instance("cfg").config == {"cmd": "old"}
    assert workspace.plugins.slash_command_registry.names() == ["old"]
    assert config_path.read_bytes() == before

    monkeypatch.setattr(
        "qwenpaw.plugins.settings.persist_plugin_settings",
        persist_plugin_settings,
    )
    report = await loader.lifecycle.update_config("cfg", {"cmd": "retry"})
    assert report.ok
    assert loader.lifecycle.get_instance("cfg").config == {"cmd": "retry"}
    assert workspace.plugins.slash_command_registry.names() == ["retry"]
    assert json.loads(config_path.read_text())["plugins"]["cfg"]["cmd"] == (
        "retry"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("save_succeeds", [False, True])
async def test_cancel_during_config_save_keeps_runtime_and_disk_consistent(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
    save_succeeds,
):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(
        "qwenpaw.constant.WORKING_DIR",
        tmp_path / "work",
    )
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_config_path",
        lambda: config_path,
    )
    persist_plugin_settings("cfg", config={"cmd": "old"})
    loader, workspace = await _load_with_workspace(
        tmp_path,
        fresh_registry,
        "cfg",
        "api.register_slash_command(api.config['cmd'], lambda c, a: None)",
        {"cmd": "old"},
    )
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    def blocked_save(*args, **kwargs):
        loop.call_soon_threadsafe(started.set)
        if not release.wait(timeout=5):
            raise TimeoutError("test did not release config writer")
        if not save_succeeds:
            raise OSError("disk write failed")
        persist_plugin_settings(*args, **kwargs)

    monkeypatch.setattr(
        "qwenpaw.plugins.settings.persist_plugin_settings",
        blocked_save,
    )
    task = asyncio.create_task(
        loader.lifecycle.update_config("cfg", {"cmd": "new"}),
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    expected = "new" if save_succeeds else "old"
    assert loader.lifecycle.get_instance("cfg").config == {"cmd": expected}
    assert workspace.plugins.slash_command_registry.names() == [expected]
    assert json.loads(config_path.read_text())["plugins"]["cfg"]["cmd"] == (
        expected
    )
    # A cancelled update must also release the lifecycle lock for a retry.
    monkeypatch.setattr(
        "qwenpaw.plugins.settings.persist_plugin_settings",
        persist_plugin_settings,
    )
    report = await asyncio.wait_for(
        loader.lifecycle.update_config("cfg", {"cmd": "retry"}),
        timeout=5,
    )
    assert report.ok


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled", [False, True])
async def test_repeated_startup_failure_preserves_config_instance_and_module(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
    cancelled,
):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_config_path",
        lambda: config_path,
    )
    persist_plugin_settings("cfg", config={"cmd": "old"})
    disk_before = config_path.read_bytes()
    body = (
        "name = api.config.get('cmd', 'default')\n"
        "        self.calls = getattr(self, 'calls', []) + [name]\n"
        "        api.register_slash_command(name, lambda c, a: None)\n"
        "        def startup():\n"
        "            if api.config.get('boom'):\n"
        "                if api.config.get('cancelled'):\n"
        "                    import asyncio\n"
        "                    raise asyncio.CancelledError()\n"
        "                raise RuntimeError('new startup failed')\n"
        "        api.register_startup_hook('cfg-start', startup)"
    )
    loader, workspace = await _load_with_workspace(
        tmp_path,
        fresh_registry,
        "cfg",
        body,
        {"cmd": "old"},
    )
    inst = loader.lifecycle.get_instance("cfg")
    record = loader.get_loaded_plugin("cfg")
    plugin = record.instance
    module_name = type(plugin).__module__
    original_module = sys.modules[module_name]
    for name in ["new-first", "new-second"]:
        config = {"cmd": name, "boom": True, "cancelled": cancelled}
        if cancelled:
            with pytest.raises(asyncio.CancelledError):
                await loader.lifecycle.update_config("cfg", config)
        else:
            report = await loader.lifecycle.update_config("cfg", config)
            assert not report.ok
            assert not report.needs_restart
            assert "new startup failed" in report.errors
        assert loader.lifecycle.get_instance("cfg") is inst
        assert loader.get_loaded_plugin("cfg") is record
        assert record.instance is plugin
        assert inst.config == {"cmd": "old"}
        assert inst.state is PluginState.ACTIVE
        assert inst.activated
        assert record.status == "active"
        assert record.enabled
        assert sys.modules[module_name] is original_module
        assert workspace.plugins.slash_command_registry.names() == ["old"]
        assert config_path.read_bytes() == disk_before
    assert plugin.calls == ["old", "new-first", "old", "new-second", "old"]
    report = await loader.lifecycle.update_config("cfg", {"cmd": "retry"})
    assert report.ok
    assert loader.lifecycle.get_instance("cfg") is inst
    assert inst.config == {"cmd": "retry"}
    assert workspace.plugins.slash_command_registry.names() == ["retry"]
    assert sys.modules[module_name] is original_module


@pytest.mark.asyncio
async def test_failed_startup_with_live_resource_does_not_restore_old_config(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    body = (
        "name = api.config.get('cmd', 'default')\n"
        "        self.calls = getattr(self, 'calls', []) + [name]\n"
        "        api.register_slash_command(name, lambda c, a: None)\n"
        "        def stop():\n"
        "            if api.config.get('boom'):\n"
        "                raise RuntimeError('resource still live')\n"
        "        api.effect('connection', None, stop)\n"
        "        def startup():\n"
        "            if api.config.get('boom'):\n"
        "                raise RuntimeError('new startup failed')\n"
        "        api.register_startup_hook('cfg-start', startup)"
    )
    loader, _ = await _load_with_workspace(
        tmp_path,
        fresh_registry,
        "cfg",
        body,
        {"cmd": "old"},
    )
    inst = loader.lifecycle.get_instance("cfg")
    record = loader.get_loaded_plugin("cfg")
    module_name = type(record.instance).__module__
    module = sys.modules[module_name]
    report = await loader.lifecycle.update_config(
        "cfg",
        {"cmd": "new", "boom": True},
    )
    assert not report.ok
    assert not report.quiescent
    assert report.needs_restart
    assert loader.lifecycle.get_instance("cfg") is inst
    assert inst.state is PluginState.FAILED
    assert inst.has_runtime_ledger()
    assert record.instance.calls == ["old", "new"]
    assert sys.modules[module_name] is module
    with pytest.raises(RuntimeError, match="not quiescent"):
        inst.refuse_unquiescent_reregister()


@pytest.mark.asyncio
@pytest.mark.parametrize("stop_fails", [False, True])
async def test_failed_config_restore_reports_resource_cleanup(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
    stop_fails,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    body = (
        "name = api.config['cmd']\n"
        "        self.calls = getattr(self, 'calls', []) + [name]\n"
        "        restoring = len(self.calls) == 3\n"
        "        def stop():\n"
        "            if restoring and self.stop_fails:\n"
        "                raise RuntimeError('restored resource still live')\n"
        "            self.alive = False\n"
        "        api.effect('connection', None, stop)\n"
        "        def startup():\n"
        "            self.alive = True\n"
        "            if len(self.calls) > 1:\n"
        "                raise RuntimeError(name + ' startup failed')\n"
        "        api.register_startup_hook('cfg-start', startup)"
    )
    plugin_id = "restore-receipt"
    loader, _ = await _load_with_workspace(
        tmp_path,
        fresh_registry,
        plugin_id,
        body,
        {"cmd": "old"},
    )
    inst = loader.lifecycle.get_instance(plugin_id)
    record = loader.get_loaded_plugin(plugin_id)
    plugin = record.instance
    plugin.stop_fails = stop_fails
    module_name = type(plugin).__module__
    module = sys.modules[module_name]

    report = await loader.lifecycle.update_config(plugin_id, {"cmd": "new"})

    assert not report.ok
    assert report.needs_restart
    assert report.quiescent is not stop_fails
    assert "new startup failed" in report.errors
    assert "restore failed: old startup failed" in report.errors
    assert any(
        "restored resource still live" in err for err in report.errors
    ) is (stop_fails)
    assert plugin.calls == ["old", "new", "old"]
    assert loader.lifecycle.get_instance(plugin_id) is inst
    assert loader.get_loaded_plugin(plugin_id) is record
    assert inst.state is PluginState.FAILED
    assert sys.modules[module_name] is module
    assert inst.has_runtime_ledger() is stop_fails
    assert plugin.alive is stop_fails

    plugin.stop_fails = False
    retried = await loader.lifecycle.unload(plugin_id, UnloadMode.UNLOAD)
    assert retried.clean and retried.quiescent
    assert not plugin.alive
    assert loader.get_loaded_plugin(plugin_id) is None


@pytest.mark.asyncio
async def test_update_config_partial_failure_keeps_old_only(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr(
        "qwenpaw.constant.WORKING_DIR",
        tmp_path / "work",
    )
    monkeypatch.setattr(
        "qwenpaw.plugins.settings.persist_plugin_settings",
        lambda *args, **kwargs: None,
    )
    body = (
        "name = api.config.get('cmd', 'old')\n"
        "        api.register_slash_command(name, lambda c, a: None)\n"
        "        if api.config.get('boom'):\n"
        "            api.register_slash_command("
        "'partial', lambda c, a: None)\n"
        "            raise RuntimeError('boom')"
    )
    loader, workspace = await _load_with_workspace(
        tmp_path,
        fresh_registry,
        "half",
        body,
        {"cmd": "old"},
    )
    report = await loader.lifecycle.update_config(
        "half",
        {"cmd": "new", "boom": True},
    )
    assert not report.ok
    names = workspace.plugins.slash_command_registry.names()
    assert "old" in names
    assert "new" not in names
    assert "partial" not in names


@pytest.mark.asyncio
async def test_update_config_refuses_legacy_hook(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr(
        "qwenpaw.constant.WORKING_DIR",
        tmp_path / "work",
    )
    monkeypatch.setattr(
        "qwenpaw.plugins.settings.persist_plugin_settings",
        lambda *args, **kwargs: None,
    )
    body = "api.register_uninstall_hook('legacy', lambda **k: None)"
    loader, _workspace = await _load_with_workspace(
        tmp_path,
        fresh_registry,
        "leg",
        body,
    )
    refused = await loader.lifecycle.update_config("leg", {"x": 1})
    assert refused.unchanged
    assert refused.requires_confirmation
    allowed = await loader.lifecycle.update_config(
        "leg",
        {"x": 1},
        confirm_legacy=True,
    )
    assert allowed.ok


@pytest.mark.asyncio
async def test_disabled_plugin_is_skipped_on_boot(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr(
        "qwenpaw.constant.WORKING_DIR",
        tmp_path / "work",
    )
    _write_plugin(tmp_path / "plugins" / "off", "off")
    loader = PluginLoader(plugin_dirs=[tmp_path / "plugins"])
    loader.registry = fresh_registry
    await loader.load_all_plugins(configs={"off": {"enabled": False}})
    assert "off" not in loader.get_all_loaded_plugins()


@pytest.mark.asyncio
async def test_set_enabled_unloads(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr(
        "qwenpaw.constant.WORKING_DIR",
        tmp_path / "work",
    )
    monkeypatch.setattr(
        "qwenpaw.plugins.settings.persist_plugin_settings",
        lambda *args, **kwargs: None,
    )
    loader, _workspace = await _load_with_workspace(
        tmp_path,
        fresh_registry,
        "sw",
        "api.register_slash_command('ping', lambda c, a: None)",
    )
    report = await loader.lifecycle.set_enabled("sw", False)
    assert report.mode is UnloadMode.UNLOAD
    assert "sw" not in loader.get_all_loaded_plugins()
