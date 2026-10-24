# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
"""File preparation must not block requests or escape failure rollback."""

import asyncio
import json
import shutil
import threading
import time

import pytest

from qwenpaw.plugins import api as plugin_api
from qwenpaw.plugins import provision, updates
from qwenpaw.plugins.architecture import PluginManifest
from qwenpaw.plugins.lifecycle import UnloadMode
from qwenpaw.plugins.loader import PluginLoader


@pytest.fixture
def provision_plugin(tmp_path, monkeypatch, fresh_registry):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    factory = tmp_path / "factory"
    factory.mkdir()
    (factory / "value.txt").write_text("factory", encoding="utf-8")
    dest = tmp_path / "target"
    root = tmp_path / "plugin"
    root.mkdir()
    metadata = {
        "id": "async-files",
        "version": "1.0.0",
        "name": "async-files",
        "entry": {"backend": "main.py"},
    }
    manifest = PluginManifest.from_dict(metadata)
    (root / "plugin.json").write_text(json.dumps(metadata), encoding="utf-8")
    loader = PluginLoader(plugin_dirs=[root.parent])
    loader.registry = fresh_registry

    def write(register):
        (root / "main.py").write_text(
            "from pathlib import Path\n"
            f"src = Path({str(factory)!r})\n"
            f"dest = Path({str(dest)!r})\n"
            "class Plugin:\n"
            "    def register(self, api):\n"
            + "".join(f"        {line}\n" for line in register.splitlines())
            + "plugin = Plugin()\n",
            encoding="utf-8",
        )
        return loader.load_plugin(manifest, root, activate=False)

    return loader, dest, write


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["declared", "async"])
async def test_file_preparation_keeps_event_loop_responsive(
    provision_plugin,
    monkeypatch,
    mode,
):
    loader, dest, write = provision_plugin
    register = (
        "async def startup():\n"
        + (
            "    branch = await api.provision_files_async(src, dest, '1')\n"
            "    assert branch == 'create'\n"
            if mode == "async"
            else ""
        )
        + "    self.value = (dest / 'value.txt').read_text()\n"
        + "api.register_startup_hook('read', startup)\n"
        + (
            "api.declare_provision_files(src, dest, '1')"
            if mode == "declared"
            else ""
        )
    )
    record = await write(register)
    assert record.status == "registered"
    assert not dest.exists()
    ticks = []
    progress = []
    original = provision.save_inventory

    def slow_save(*args, **kwargs):
        before = len(ticks)
        time.sleep(0.08)
        progress.append(len(ticks) > before)
        return original(*args, **kwargs)

    async def heartbeat():
        while True:
            ticks.append(None)
            await asyncio.sleep(0.005)

    monkeypatch.setattr(provision, "save_inventory", slow_save)
    task = asyncio.create_task(heartbeat())
    try:
        await loader.lifecycle.activate("async-files")
        assert record.instance.value == "factory"
        assert progress and all(progress)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await loader.lifecycle.unload("async-files", UnloadMode.UNINSTALL)


@pytest.mark.asyncio
async def test_unactivated_declaration_does_not_create_files(provision_plugin):
    loader, dest, write = provision_plugin
    record = await write("api.declare_provision_files(src, dest, '1')")
    assert record.status == "registered"
    report = await loader.lifecycle.unload("async-files", UnloadMode.UNINSTALL)
    assert report.clean
    assert not dest.exists()
    assert not provision.load_inventory("async-files").get("locations")


@pytest.mark.asyncio
@pytest.mark.parametrize("user_owned", [False, True])
async def test_partial_declarations_rollback_only_created_files(
    provision_plugin,
    user_owned,
):
    loader, dest, write = provision_plugin
    if user_owned:
        dest.mkdir()
        (dest / "value.txt").write_text("user", encoding="utf-8")
    await write(
        "api.declare_provision_files(src, dest, '1')\n"
        "api.declare_provision_files(src / 'missing', dest / 'second', '1')",
    )
    with pytest.raises(Exception):
        await loader.lifecycle.activate("async-files")
    assert dest.exists() is user_owned
    if user_owned:
        assert (dest / "value.txt").read_text(encoding="utf-8") == "user"
    else:
        assert str(dest) not in provision.load_inventory("async-files").get(
            "locations",
            {},
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["declared", "async"])
async def test_cancelled_preparation_waits_for_worker_and_rolls_back(
    provision_plugin,
    monkeypatch,
    mode,
):
    loader, dest, write = provision_plugin
    register = "api.declare_provision_files(src, dest, '1')"
    if mode == "async":
        register = (
            "async def startup():\n"
            "    await api.provision_files_async(src, dest, '1')\n"
            "api.register_startup_hook('prepare', startup)"
        )
    await write(register)
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    original = provision.save_inventory

    def blocked_save(*args, **kwargs):
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(2)
        return original(*args, **kwargs)

    monkeypatch.setattr(provision, "save_inventory", blocked_save)
    task = asyncio.create_task(loader.lifecycle.activate("async-files"))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not dest.exists()
    assert str(dest) not in provision.load_inventory("async-files").get(
        "locations",
        {},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["activation", "swap"])
async def test_transaction_disk_preparation_runs_off_loop(
    provision_plugin,
    monkeypatch,
    tmp_path,
    phase,
):
    # pylint: disable=protected-access
    loader, _, write = provision_plugin
    await write("pass")
    main_thread = threading.get_ident()
    calls = []

    def watch(owner, name):
        original = getattr(owner, name)

        def checked(*args, **kwargs):
            assert threading.get_ident() != main_thread, name
            calls.append(name)
            return original(*args, **kwargs)

        monkeypatch.setattr(owner, name, checked)

    if phase == "activation":
        expected = {
            "snapshot_tool_inventory",
            "snapshot_location_keys",
            "snapshot_agent_tool_configs",
        }
        watch(provision, "snapshot_tool_inventory")
        watch(provision, "snapshot_location_keys")
        watch(plugin_api, "snapshot_agent_tool_configs")
        await loader.lifecycle.activate("async-files")
    else:
        expected = {"_load_manifest", "write_updating_marker"}
        incoming = tmp_path / "incoming"
        shutil.copytree(tmp_path / "plugin", incoming)
        watch(loader, "_load_manifest")
        watch(updates, "write_updating_marker")
        await loader._swap_plugin_dir(
            "async-files",
            tmp_path / "plugin",
            incoming,
        )
    assert set(calls) == expected
