# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Probe import, reload rollback, and provision migration."""

from __future__ import annotations

import asyncio
import json
import importlib.util
import os
import py_compile
import shutil
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.plugins.architecture import PluginManifest
from qwenpaw.plugins.lifecycle import PluginInstance, UnloadMode
from qwenpaw.plugins.loader import PluginLoader
from qwenpaw.memory import MemoryBackendRegistry
from qwenpaw.plugins.module_isolation import (
    finish_probe_import,
    get_namespace_finder,
    plugin_module_name,
    probe_plugin_source,
)
from qwenpaw.plugins.provision import (
    apply_tool_factory,
    commit_migrations,
    load_inventory,
    provision_files,
    recover_migrating_inventory,
)
from qwenpaw.plugins.updates import (
    marker_path,
    recover_interrupted_updates,
    update_marker_status,
    write_updating_marker,
)
from qwenpaw.plugins.workspace_projector import WorkspaceProjector
from qwenpaw.runtime.slash_command_registry import SlashCommandRegistry

from .timing import WAIT_TIMEOUT


def _write_plugin(
    root: Path,
    plugin_id: str,
    *,
    body: str = "pass",
    extra_py: str | None = None,
    version: str = "1.0.0",
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "id": plugin_id,
                "version": version,
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
    if extra_py is not None:
        (root / "helper.py").write_text(extra_py, encoding="utf-8")
    return root


@pytest.mark.asyncio
@pytest.mark.parametrize("incoming_id", ["renamed", "different"])
async def test_in_place_reload_reads_incoming_manifest(
    tmp_path,
    fresh_registry,
    monkeypatch,
    incoming_id,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    stopped = tmp_path / "stopped"
    root = _write_plugin(
        tmp_path / "plugins" / "renamed",
        "renamed",
        body=(
            "self.value = lambda: 'old'\n"
            "        api.register_shutdown_hook('stop', "
            f"lambda: open({str(stopped)!r}, 'w').close())"
        ),
    )
    loader = PluginLoader([root.parent])
    loader.registry = fresh_registry
    manifest_data = json.loads((root / "plugin.json").read_text())
    original = await loader.load_plugin(
        PluginManifest.from_dict(manifest_data),
        root,
    )
    try:
        manifest_data.update(id=incoming_id, version="2.0.0")
        manifest_data["entry"]["backend"] = "new_main.py"
        (root / "plugin.json").write_text(json.dumps(manifest_data))
        (root / "new_main.py").write_text(
            "class Plugin:\n"
            "    def register(self, api):\n"
            "        self.value = lambda: 'new'\n"
            "plugin = Plugin()\n",
        )
        (root / "main.py").unlink()
        report = await loader.lifecycle.reload("renamed")
        current = loader.get_loaded_plugin("renamed")
        if incoming_id == "renamed":
            assert report.ok, report.errors
            assert current.instance.value() == "new"
            assert current.manifest.version == "2.0.0"
            assert stopped.exists()
        else:
            assert not report.ok and report.unchanged
            assert any("id" in error.lower() for error in report.errors)
            assert current is original and current.status == "active"
            assert current.instance.value() == "old"
            assert not stopped.exists()
    finally:
        await loader.unload_plugin("renamed")


@pytest.mark.asyncio
async def test_in_place_failed_start_restores_object_without_old_entry(
    tmp_path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    root = _write_plugin(
        tmp_path / "plugins" / "restore-entry",
        "restore-entry",
        body=(
            "self.value = api.config['value']\n"
            "        def start():\n"
            "            self.starts = getattr(self, 'starts', 0) + 1\n"
            "        api.register_startup_hook('start', start)"
        ),
    )
    loader = PluginLoader([root.parent])
    loader.registry = fresh_registry
    manifest_data = json.loads((root / "plugin.json").read_text())
    original = await loader.load_plugin(
        PluginManifest.from_dict(manifest_data),
        root,
        config={"value": "old"},
    )
    generation = loader.lifecycle.get_instance("restore-entry").generation
    try:
        manifest_data.update(version="2.0.0", entry={"backend": "new_main.py"})
        (root / "plugin.json").write_text(json.dumps(manifest_data))
        (root / "main.py").unlink()
        (root / "new_main.py").write_text(
            "class Plugin:\n"
            "    def register(self, api):\n"
            "        def start():\n"
            "            raise RuntimeError('new startup failed')\n"
            "        api.register_startup_hook('start', start)\n"
            "plugin = Plugin()\n",
        )
        report = await loader.lifecycle.reload(
            "restore-entry",
            config={"value": "new"},
        )
        current = loader.get_loaded_plugin("restore-entry")
        restored = loader.lifecycle.get_instance("restore-entry")
        assert not report.ok and not report.needs_restart
        assert any("new startup failed" in error for error in report.errors)
        assert any("previous service was restored" in e for e in report.errors)
        assert current.status == "active" and restored.activated
        assert current.instance is original.instance
        assert current.instance.value == "old" and current.instance.starts == 2
        assert current.manifest.version == "1.0.0"
        assert restored.config == {"value": "old"}
        assert restored.generation == generation
        assert not (root / "main.py").exists()
        # Fresh loads still require source; object recovery does not.
        fresh_loader = PluginLoader([root.parent])
        with pytest.raises(
            FileNotFoundError,
            match="entry point files not found",
        ):
            await fresh_loader.load_plugin(original.manifest, root)
    finally:
        await loader.unload_plugin("restore-entry")


def _link_cached_sources(root, linked_source, entry, helper):
    if linked_source == "backend":
        target = root / "actual_backend"
        target.mkdir()
        entry.write_text(
            entry.read_text().replace(".helper", ".backend.helper"),
        )
        entry.rename(target / entry.name)
        helper.rename(target / helper.name)
        (root / "backend").symlink_to(target.name, target_is_directory=True)
        manifest = json.loads((root / "plugin.json").read_text())
        manifest["entry"]["backend"] = "backend/main.py"
        (root / "plugin.json").write_text(json.dumps(manifest))
        return root / "backend/main.py", root / "backend/helper.py"
    if linked_source:
        link = root / linked_source
        target = root / "implementation.py"
        link.rename(target)
        link.symlink_to(target.name)
    return entry, helper


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("linked_source", "external_cache"),
    [
        (None, False),
        ("main.py", False),
        ("helper.py", False),
        ("backend", False),
        ("backend", True),
    ],
)
async def test_reload_ignores_same_size_same_mtime_bytecode(
    tmp_path,
    fresh_registry,
    monkeypatch,
    linked_source,
    external_cache,
):
    if external_cache:
        monkeypatch.setattr(sys, "pycache_prefix", str(tmp_path / "cache"))
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    observed = tmp_path / "imports.log"
    root = _write_plugin(tmp_path / "plugins" / "cached", "cached")
    entry = root / "main.py"
    helper = root / "helper.py"
    entry.write_text(
        "from .helper import VALUE\n"
        "ENTRY = 'old'\n"
        f"with open({str(observed)!r}, 'a') as log:\n"
        "    log.write(f'{__name__}:{ENTRY}:{VALUE}\\n')\n"
        "class Plugin:\n"
        "    def register(self, api):\n"
        "        self.value = (ENTRY, VALUE)\n"
        "plugin = Plugin()\n",
    )
    helper.write_text("VALUE = 'old'\n")
    entry, helper = _link_cached_sources(root, linked_source, entry, helper)
    vendor = root / ".venv" / "lib" / "vendor.py"
    vendor.parent.mkdir(parents=True)
    vendor.write_text("VALUE = 'third-party'\n")
    if external_cache:
        (root / "dependency_alias").symlink_to(
            ".venv",
            target_is_directory=True,
        )
        (root / "actual_backend" / "cycle").symlink_to(
            "..",
            target_is_directory=True,
        )
        vendor = root / "dependency_alias" / "lib" / "vendor.py"
    vendor_cache = Path(py_compile.compile(str(vendor), doraise=True))
    vendor_before = vendor_cache.read_bytes(), vendor_cache.stat().st_mtime_ns
    for source in (entry, helper):
        py_compile.compile(str(source), doraise=True)
    loader = PluginLoader([root.parent])
    loader.registry = fresh_registry
    manifest = PluginManifest.from_dict(
        json.loads((root / "plugin.json").read_text()),
    )
    await loader.load_plugin(manifest, root)
    try:
        assert loader.get_loaded_plugin("cached").instance.value == (
            "old",
            "old",
        )
        assert all(
            Path(importlib.util.cache_from_source(str(source))).exists()
            for source in (entry, helper)
        )
        for source in (entry, helper):
            previous = source.stat()
            source.write_text(source.read_text().replace("'old'", "'new'"))
            os.utime(source, ns=(previous.st_atime_ns, previous.st_mtime_ns))
            assert source.stat().st_size == previous.st_size
        observed.write_text("")
        report = await loader.lifecycle.reload("cached")
        assert report.ok
        assert loader.get_loaded_plugin("cached").instance.value == (
            "new",
            "new",
        )
        assert observed.read_text().splitlines() == [
            "plugin_cached__probe:new:new",
            "plugin_cached:new:new",
        ]
        if linked_source:
            assert (root / linked_source).is_symlink()
        assert (
            vendor_cache.read_bytes(),
            vendor_cache.stat().st_mtime_ns,
        ) == vendor_before
    finally:
        await loader.unload_plugin("cached")


@pytest.mark.asyncio
async def test_reload_preserves_locked_bytecode_and_uses_new_source(
    tmp_path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    installed = _write_plugin(
        tmp_path / "plugins" / "cached",
        "cached",
        body="self.value = 'old'; self.api = api",
    )
    incoming = _write_plugin(
        tmp_path / "incoming",
        "cached",
        body="self.value = 'new'",
        version="2.0.0",
    )
    cache = Path(py_compile.compile(str(incoming / "main.py"), doraise=True))
    cached_before = (cache.read_bytes(), cache.stat().st_mtime_ns)
    delete_attempts = []
    loader = PluginLoader([installed.parent])
    loader.registry = fresh_registry
    manifest = PluginManifest.from_dict(
        json.loads((installed / "plugin.json").read_text()),
    )
    original = await loader.load_plugin(manifest, installed)
    unlink = Path.unlink

    def deny_cache_delete(path, *args, **kwargs):
        if path.suffix == ".pyc" and incoming in path.parents:
            delete_attempts.append(path)
            raise PermissionError("bytecode cache locked")
        return unlink(path, *args, **kwargs)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(Path, "unlink", deny_cache_delete)
            report = await loader.lifecycle.reload(
                "cached",
                new_source=incoming,
            )
        assert report.ok
        assert not report.unchanged
        assert not delete_attempts
        assert (cache.read_bytes(), cache.stat().st_mtime_ns) == cached_before
        current = loader.get_loaded_plugin("cached")
        assert current is not original
        assert current.instance.value == "new"
        with pytest.raises(
            RuntimeError,
            match="new registrations are forbidden",
        ):
            original.instance.api.register_slash_command(
                "stale",
                lambda *_: None,
            )
        assert not marker_path("cached").exists()
    finally:
        await loader.unload_plugin("cached")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "broken_code",
    ["def (\n", "raise RuntimeError('module boom')\n"],
    ids=["syntax", "module-level"],
)
async def test_probe_failure_keeps_old(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
    broken_code,
):
    monkeypatch.setattr(
        "qwenpaw.constant.WORKING_DIR",
        tmp_path / "work",
    )
    installed = _write_plugin(
        tmp_path / "plugins" / "keep-old",
        "keep-old",
        body="api.register_slash_command('ping', lambda c, a: None)",
    )
    workspace = SimpleNamespace(
        agent_id="talk",
        plugins=SimpleNamespace(
            slash_command_registry=SlashCommandRegistry(),
        ),
    )
    fresh_registry.projector = WorkspaceProjector(
        live_workspaces=lambda: [workspace],
    )
    fresh_registry.set_workspace_manager(
        SimpleNamespace(agents={"talk": workspace}),
    )
    loader = PluginLoader(plugin_dirs=[tmp_path / "plugins"])
    loader.registry = fresh_registry
    manifest = PluginManifest.from_dict(
        json.loads((installed / "plugin.json").read_text(encoding="utf-8")),
    )
    await loader.load_plugin(manifest, installed)
    await fresh_registry.projector.project(
        "slash_command",
        "ping",
        "keep-old",
    )
    assert "ping" in workspace.plugins.slash_command_registry.names()

    broken = tmp_path / "staging-broken"
    _write_plugin(broken, "keep-old", body="pass")
    (broken / "main.py").write_text(broken_code, encoding="utf-8")

    report = await loader.lifecycle.reload(
        "keep-old",
        new_source=broken,
    )
    assert report.unchanged
    assert not report.ok
    assert "keep-old" in loader.get_all_loaded_plugins()
    assert "keep-old" in fresh_registry.get_all_plugin_manifests()
    assert "ping" in workspace.plugins.slash_command_registry.names()
    assert (
        (installed / "main.py")
        .read_text(encoding="utf-8")
        .count(
            "register_slash_command",
        )
    )


def test_probe_cleans_finder_and_modules(tmp_path: Path):
    root = _write_plugin(tmp_path / "probe-me", "probe-me")
    probe_plugin_source("probe-me", root, root / "main.py")
    probe_name = plugin_module_name("probe-me", probe=True)
    assert not get_namespace_finder().is_registered(probe_name)
    assert probe_name not in sys.modules
    finish_probe_import("probe-me", root)
    assert not get_namespace_finder().is_registered(probe_name)


def test_updating_marker_restores_old_directory(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "qwenpaw.constant.WORKING_DIR",
        tmp_path / "work",
    )
    target = tmp_path / "plugins" / "mid"
    target.mkdir(parents=True)
    (target / "main.py").write_text("NEW\n", encoding="utf-8")
    backup = tmp_path / "plugins" / "mid.bak"
    backup.mkdir()
    (backup / "main.py").write_text("OLD\n", encoding="utf-8")
    write_updating_marker(
        "mid",
        backup_path=backup,
        target_path=target,
    )
    assert recover_interrupted_updates() == ["mid"]
    assert (target / "main.py").read_text(encoding="utf-8") == "OLD\n"
    assert not backup.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("interrupted_at", ["copy", "move"])
async def test_boot_recovers_only_before_swap_starts(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
    interrupted_at: str,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    plugin_id = f"interrupted-staging-{interrupted_at}"
    installed = _write_plugin(
        tmp_path / "plugins" / plugin_id,
        plugin_id,
        body="self.version = 'old'",
    )
    incoming = _write_plugin(
        tmp_path / "incoming",
        plugin_id,
        body="self.version = 'new'",
        version="2.0.0",
    )
    loader = PluginLoader([installed.parent])
    loader.registry = fresh_registry

    class InterruptedProcess(BaseException):
        pass

    def interrupt_copy(_source, destination):
        Path(destination).mkdir()
        (Path(destination) / "partial").write_text("incomplete")
        raise InterruptedProcess

    def interrupt_move(_source, _destination):
        raise InterruptedProcess

    with monkeypatch.context() as patch:
        patch.setattr(
            shutil,
            "copytree" if interrupted_at == "copy" else "move",
            interrupt_copy if interrupted_at == "copy" else interrupt_move,
        )
        with pytest.raises(InterruptedProcess):
            await loader._swap_plugin_dir(plugin_id, installed, incoming)

    marker = json.loads(marker_path(plugin_id).read_text())
    assert not Path(marker["backup_path"]).exists()
    boot_loader = PluginLoader([installed.parent])
    boot_loader.registry = fresh_registry
    await boot_loader.load_all_plugins(activate=True)
    record = boot_loader.get_loaded_plugin(plugin_id)
    if interrupted_at == "copy":
        assert record.status == "active"
        assert record.manifest.version == "1.0.0"
        assert sys.modules[plugin_module_name(plugin_id)].plugin.version == (
            "old"
        )
        assert not Path(marker["staging_path"]).exists()
        assert not marker_path(plugin_id).exists()
    else:
        assert record.status == "failed"
        assert "needs_restart" in record.diagnostics
        assert plugin_module_name(plugin_id) not in sys.modules
        assert marker_path(plugin_id).exists()
    assert marker["phase"] == (
        "staging" if interrupted_at == "copy" else "swapping"
    )


def test_tool_fields_follow_plugin_keep_user(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "qwenpaw.constant.WORKING_DIR",
        tmp_path / "work",
    )
    apply_tool_factory(
        "tid",
        "demo",
        {
            "description": "old",
            "icon": "a",
            "display_to_user": True,
            "enabled": False,
            "async_execution": False,
            "config": {},
        },
        None,
    )
    merged = apply_tool_factory(
        "tid",
        "demo",
        {
            "description": "new",
            "icon": "b",
            "display_to_user": True,
            "enabled": False,
            "async_execution": False,
            "config": {},
        },
        {
            "description": "old",
            "icon": "a",
            "display_to_user": True,
            "enabled": True,
            "async_execution": True,
            "config": {"k": 1},
        },
    )
    assert merged["description"] == "new"
    assert merged["icon"] == "b"
    assert merged["enabled"] is True
    assert merged["async_execution"] is True
    assert merged["config"] == {"k": 1}


def test_provision_register_failure_keeps_user_edits(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setattr(
        "qwenpaw.constant.WORKING_DIR",
        tmp_path / "work",
    )
    src = tmp_path / "src"
    src.mkdir()
    (src / "note.md").write_text("v1\n", encoding="utf-8")
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "note.md").write_text("v1\n", encoding="utf-8")
    provision_files("pid", src, dest, "1.0.0")
    (dest / "note.md").write_text("user\n", encoding="utf-8")
    (src / "note.md").write_text("v2\n", encoding="utf-8")
    assert provision_files("pid", src, dest, "2.0.0") == "migrate"
    assert (dest / "note.md").read_text(encoding="utf-8") == "user\n"
    recover_migrating_inventory("pid")
    assert (dest / "note.md").read_text(encoding="utf-8") == "user\n"


@pytest.mark.asyncio
async def test_reload_rollback_leaves_old_on_disk(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr(
        "qwenpaw.constant.WORKING_DIR",
        tmp_path / "work",
    )
    installed = _write_plugin(
        tmp_path / "plugins" / "roll",
        "roll",
        body="pass",
    )
    old_text = (installed / "main.py").read_text(encoding="utf-8")
    loader = PluginLoader(plugin_dirs=[tmp_path / "plugins"])
    loader.registry = fresh_registry
    manifest = PluginManifest.from_dict(
        json.loads((installed / "plugin.json").read_text(encoding="utf-8")),
    )
    await loader.load_plugin(manifest, installed)

    staging = _write_plugin(
        tmp_path / "staging-roll",
        "roll",
        body="raise RuntimeError('register boom')",
    )
    report = await loader.lifecycle.reload("roll", new_source=staging)
    assert not report.ok
    assert not report.unchanged
    assert (installed / "main.py").read_text(encoding="utf-8") == old_text
    assert "roll" in loader.get_all_loaded_plugins()
    assert any("previous service was restored" in e for e in report.errors)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "link_kind",
    ["root", "owned-root", "relative-root", "file", "directory"],
)
async def test_failed_reload_preserves_user_symlinks_and_external_data(
    tmp_path,
    fresh_registry,
    monkeypatch,
    link_kind,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    plugin_id, dest = "linked-migration", tmp_path / "dest"
    monkeypatch.chdir(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    (external / "note.txt").write_text("v1")
    relative = (
        Path("nested/note.txt")
        if link_kind == "directory"
        else Path("note.txt")
    )
    factories = []
    for version in ("v1", "v2"):
        factory = tmp_path / version
        (factory / relative).parent.mkdir(parents=True)
        (factory / relative).write_text(version)
        (factory / "plain.txt").write_text(version)
        factories.append(factory)
    if link_kind in {"root", "owned-root", "relative-root"}:
        if link_kind == "owned-root":
            provision_files(plugin_id, factories[0], dest, "1.0.0")
            shutil.rmtree(dest)
        dest.symlink_to(external, target_is_directory=True)
        assert (
            provision_files(plugin_id, factories[0], dest, "1.0.0") == "keep"
        )
        link = dest
    else:
        provision_files(plugin_id, factories[0], dest, "1.0.0")
        link = dest / ("nested" if link_kind == "directory" else relative)
        if link.is_dir():
            shutil.rmtree(link)
            link.symlink_to(external, target_is_directory=True)
        else:
            link.unlink()
            link.symlink_to(external / "note.txt")
    link_target = link.readlink()
    api_dest = "dest" if link_kind == "relative-root" else str(dest)
    installed = _write_plugin(
        tmp_path / "plugins" / plugin_id,
        plugin_id,
        body=(
            f"api.provision_files({str(factories[0])!r}, "
            f"{api_dest!r}, '1.0.0')"
        ),
    )
    loader = PluginLoader([installed.parent])
    loader.registry = fresh_registry
    manifest = PluginManifest.from_dict(
        json.loads((installed / "plugin.json").read_text()),
    )
    await loader.load_plugin(manifest, installed)
    staging = _write_plugin(
        tmp_path / "staging",
        plugin_id,
        version="2.0.0",
        body=(
            f"api.provision_files({str(factories[1])!r}, "
            f"{api_dest!r}, '2.0.0')\n"
            "        raise RuntimeError('new register failed')"
        ),
    )
    try:
        report = await loader.lifecycle.reload(plugin_id, new_source=staging)
        assert not report.ok
        assert link.is_symlink() and link.readlink() == link_target
        assert (external / "note.txt").read_text() == "v1"
        assert sorted(path.name for path in external.iterdir()) == ["note.txt"]
        record = loader.get_loaded_plugin(plugin_id)
        assert record.status == "active" and record.manifest.version == "1.0.0"
        assert load_inventory(plugin_id)["locations"][str(dest)]["owned"] is (
            link_kind not in {"root", "relative-root"}
        )
        if link_kind not in {"root", "owned-root", "relative-root"}:
            assert (dest / "plain.txt").read_text() == "v1"
    finally:
        await loader.lifecycle.unload(plugin_id, UnloadMode.UNLOAD)


def test_commit_migrations_clears_marker(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "qwenpaw.constant.WORKING_DIR",
        tmp_path / "work",
    )
    src = tmp_path / "s"
    src.mkdir()
    (src / "a.txt").write_text("1\n", encoding="utf-8")
    dest = tmp_path / "d"
    dest.mkdir()
    (dest / "a.txt").write_text("1\n", encoding="utf-8")
    provision_files("cid", src, dest, "1.0.0")
    (src / "a.txt").write_text("2\n", encoding="utf-8")
    provision_files("cid", src, dest, "2.0.0")
    loc = load_inventory("cid")["locations"][str(dest)]
    assert loc.get("migrating")
    commit_migrations("cid")
    loc = load_inventory("cid")["locations"][str(dest)]
    assert loc.get("migrating") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("plugin_type", ["channel", "memory"])
async def test_two_phase_boot_keeps_current_provision_migration(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
    plugin_type: str,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    plugin_id = f"two-phase-{plugin_type}"
    source = tmp_path / "factory"
    source.mkdir()
    (source / "version.txt").write_text("1.0.0")
    dest = tmp_path / "data"
    provision_files(plugin_id, source, dest, "1.0.0")
    (source / "version.txt").write_text("2.0.0")
    installed = _write_plugin(
        tmp_path / "plugins" / plugin_id,
        plugin_id,
        version="2.0.0",
        body=(f"api.provision_files({str(source)!r}, {str(dest)!r}, '2.0.0')"),
    )
    manifest = json.loads((installed / "plugin.json").read_text())
    manifest["type"] = plugin_type
    (installed / "plugin.json").write_text(json.dumps(manifest))
    loader = PluginLoader([installed.parent])
    loader.registry = fresh_registry

    await loader.load_all_plugins(types=["channel", "memory"])
    record = loader.get_loaded_plugin(plugin_id)
    location = load_inventory(plugin_id)["locations"][str(dest)]
    assert record.status == "registered"
    assert location["migrating"]["status"] == "prepared"
    backup = Path(location["migrating"]["backup_path"])
    assert (dest / "version.txt").read_text() == "2.0.0"

    await loader.load_all_plugins()
    assert loader.get_loaded_plugin(plugin_id) is record
    location = load_inventory(plugin_id)["locations"][str(dest)]
    assert location["version"] == "2.0.0"
    assert location["migrating"]["status"] == "prepared"
    assert backup.exists()
    assert (dest / "version.txt").read_text() == "2.0.0"

    await loader.activate_all_loaded()
    assert record.status == "active"
    assert record.manifest.version == "2.0.0"
    location = load_inventory(plugin_id)["locations"][str(dest)]
    assert location["version"] == "2.0.0"
    assert location["migrating"] is None
    assert not backup.exists()
    assert (dest / "version.txt").read_text() == "2.0.0"


@pytest.mark.asyncio
async def test_boot_recovers_leftover_provision_under_lifecycle_lock(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    plugin_id = "locked-boot-recovery"
    source = tmp_path / "factory"
    source.mkdir()
    (source / "version.txt").write_text("1.0.0")
    dest = tmp_path / "data"
    provision_files(plugin_id, source, dest, "1.0.0")
    (source / "version.txt").write_text("2.0.0")
    provision_files(plugin_id, source, dest, "2.0.0")
    location = load_inventory(plugin_id)["locations"][str(dest)]
    backup = Path(location["migrating"]["backup_path"])
    installed = _write_plugin(tmp_path / "plugins" / plugin_id, plugin_id)
    loader = PluginLoader([installed.parent])
    loader.registry = fresh_registry

    async with loader.plugin_lifecycle(plugin_id):
        recovery = asyncio.create_task(loader.load_all_plugins(activate=True))
        await asyncio.sleep(0.05)
        pending = not recovery.done()
        content_while_locked = (dest / "version.txt").read_text()
        backup_while_locked = backup.exists()
    await asyncio.wait_for(recovery, timeout=WAIT_TIMEOUT)
    assert pending
    assert content_while_locked == "2.0.0"
    assert backup_while_locked
    assert loader.get_loaded_plugin(plugin_id).status == "active"
    location = load_inventory(plugin_id)["locations"][str(dest)]
    assert location["version"] == "1.0.0"
    assert location["migrating"] is None
    assert (dest / "version.txt").read_text() == "1.0.0"
    assert not backup.exists()


@pytest.mark.asyncio
async def test_reload_restore_failure_preserves_backups_and_blocks_activation(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    from qwenpaw.plugins import provision as provision_module

    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    plugin_id = "restore-blocked"
    dest = tmp_path / "data"
    trace = tmp_path / "startup"
    for version in ("1.0.0", "2.0.0"):
        factory = tmp_path / version
        factory.mkdir()
        (factory / "version.txt").write_text(version, encoding="utf-8")
    installed = _write_plugin(
        tmp_path / "plugins" / plugin_id,
        plugin_id,
        body=(
            "from pathlib import Path\n"
            f"        if not Path({str(dest)!r}).exists():\n"
            f"            api.provision_files({str(tmp_path / '1.0.0')!r}, "
            f"{str(dest)!r}, '1.0.0')\n"
            "        api.register_startup_hook('note', "
            f"lambda: Path({str(trace)!r}).write_text('old started'))"
        ),
    )
    loader = PluginLoader(plugin_dirs=[installed.parent])
    loader.registry = fresh_registry
    manifest = PluginManifest.from_dict(
        json.loads((installed / "plugin.json").read_text(encoding="utf-8")),
    )
    assert (await loader.load_plugin(manifest, installed)).status == "active"
    trace.unlink()
    staging = _write_plugin(
        tmp_path / "staging",
        plugin_id,
        version="2.0.0",
        body=(
            f"api.provision_files({str(tmp_path / '2.0.0')!r}, "
            f"{str(dest)!r}, '2.0.0')\n"
            "        raise RuntimeError('register boom')"
        ),
    )

    def deny_restore(_backup, _dest):
        raise PermissionError("provision restore occupied")

    restore_backup = provision_module._restore_backup
    monkeypatch.setattr(provision_module, "_restore_backup", deny_restore)
    report = await loader.lifecycle.reload(plugin_id, new_source=staging)
    assert not report.ok
    assert report.needs_restart
    assert any("register boom" in error for error in report.errors)
    assert any("previous service was not restored" in e for e in report.errors)
    assert any(
        "provision restore occupied" in error for error in report.errors
    )
    assert not trace.exists(), "old service must wait for disk recovery"
    record = loader.get_loaded_plugin(plugin_id)
    assert record is not None and record.status == "failed"
    assert any(
        "provision restore occupied" in item for item in record.diagnostics
    )
    location = load_inventory(plugin_id)["locations"][str(dest)]
    assert location["migrating"]["status"] == "prepared"
    backup = Path(location["migrating"]["backup_path"])
    assert (backup / "version.txt").read_text(encoding="utf-8") == "1.0.0"
    marker = json.loads(marker_path(plugin_id).read_text(encoding="utf-8"))
    assert marker["status"] == "prepared"
    assert Path(marker["backup_path"]).is_dir()
    with pytest.raises(RuntimeError):
        await loader.lifecycle.activate(plugin_id)
    assert not trace.exists()

    monkeypatch.setattr(provision_module, "_restore_backup", restore_backup)
    restarted = PluginLoader(plugin_dirs=[installed.parent])
    restarted.registry = fresh_registry
    await restarted.load_all_plugins(activate=True)
    assert restarted.get_loaded_plugin(plugin_id).status == "active"
    assert trace.read_text(encoding="utf-8") == "old started"
    assert (dest / "version.txt").read_text(encoding="utf-8") == "1.0.0"
    assert not backup.exists()
    assert not marker_path(plugin_id).exists()


@pytest.fixture()
def pending_migrations(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    plugin_id = "cleanup"
    dests = []
    backups = []
    for name in ("occupied", "available"):
        src = tmp_path / f"src-{name}"
        src.mkdir()
        (src / "version.txt").write_text("old", encoding="utf-8")
        dest = tmp_path / name
        provision_files(plugin_id, src, dest, "1")
        (src / "version.txt").write_text("new", encoding="utf-8")
        provision_files(plugin_id, src, dest, "2")
        dests.append(dest)
        marker = load_inventory(plugin_id)["locations"][str(dest)]["migrating"]
        backups.append(Path(marker["backup_path"]))
    return plugin_id, dests, backups


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["activate", "provision", "plugin"])
async def test_committed_cleanup_failure_keeps_retry_locations(
    tmp_path: Path,
    monkeypatch,
    fresh_registry,
    pending_migrations,
    entry: str,
):
    from qwenpaw.plugins import loader as loader_module
    from qwenpaw.plugins import provision as provision_module

    plugin_id, dests, backups = pending_migrations
    loader = PluginLoader(plugin_dirs=[])
    loader.registry = fresh_registry
    plugin_backup = tmp_path / "plugin.bak"
    plugin_backup.mkdir()
    target = _write_plugin(tmp_path / "plugin", plugin_id)
    if entry != "activate":
        write_updating_marker(
            plugin_id,
            backup_path=plugin_backup,
            target_path=target,
        )
    blocked = plugin_backup if entry == "plugin" else backups[0]
    module = loader_module if entry == "plugin" else provision_module
    attribute = "_remove_dir" if entry == "plugin" else "_remove_path"
    remove = getattr(module, attribute)

    def deny_occupied(path):
        if path == blocked:
            raise PermissionError("backup occupied")
        return remove(path)

    monkeypatch.setattr(module, attribute, deny_occupied)
    committed = [None]
    if entry == "activate":
        errors = await loader._commit_plugin_transaction(
            plugin_id,
            committed=committed,
        )
        assert committed[0] == errors
        assert not marker_path(plugin_id).exists()
    else:
        errors = await loader._finish_committed_reload(
            plugin_id,
            plugin_backup,
        )
        assert update_marker_status(plugin_id) == "committed"
        assert plugin_backup.is_dir()
    assert any("backup occupied" in error for error in errors)
    locations = load_inventory(plugin_id)["locations"]
    assert locations[str(dests[1])]["migrating"] is None
    assert not backups[1].exists()
    if entry != "plugin":
        assert locations[str(dests[0])]["migrating"]["status"] == "committed"
        assert backups[0].is_dir()

    monkeypatch.setattr(module, attribute, remove)
    if entry == "activate":
        recovery = recover_migrating_inventory(plugin_id)
        assert not recovery.failures
    else:
        assert (
            await loader._finish_committed_reload(plugin_id, plugin_backup)
            == []
        )
        assert not marker_path(plugin_id).exists()
        assert not plugin_backup.exists()
    for dest, backup in zip(dests, backups):
        assert (dest / "version.txt").read_text(encoding="utf-8") == "new"
        assert not backup.exists()
        assert (
            load_inventory(plugin_id)["locations"][str(dest)]["migrating"]
            is None
        )


@pytest.mark.asyncio
async def test_effect_is_torn_down_on_unload():
    inst = PluginInstance("fx")
    state = {"on": False}

    def setup():
        state["on"] = True

    def teardown():
        state["on"] = False

    inst.record_runtime(
        "patch",
        teardown,
        shutdown_critical=False,
        kind="effect",
    )
    setup()
    assert state["on"]
    await inst.dispose(UnloadMode.UNLOAD)
    assert state["on"] is False


def _write_provision_plugin(
    root: Path,
    plugin_id: str,
    dest: Path,
    version: str,
    content: str,
    *,
    boom: bool = False,
) -> Path:
    factory = root / "factory"
    factory.mkdir(parents=True, exist_ok=True)
    (factory / "note.md").write_text(content, encoding="utf-8")
    boom_line = "        raise RuntimeError('register boom')\n" if boom else ""
    body = (
        "from pathlib import Path\n"
        f"        dest = Path({str(dest)!r})\n"
        "        api.provision_files(\n"
        "            Path(__file__).parent / 'factory', dest, "
        f"{version!r},\n"
        "        )\n"
        f"{boom_line}"
    )
    return _write_plugin(root, plugin_id, body=body)


@pytest.mark.asyncio
async def test_reload_register_failure_keeps_user_provision(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr(
        "qwenpaw.constant.WORKING_DIR",
        tmp_path / "work",
    )
    dest = tmp_path / "notes"
    installed = _write_provision_plugin(
        tmp_path / "plugins" / "prov",
        "prov",
        dest,
        "1.0.0",
        "v1\n",
    )
    loader = PluginLoader(plugin_dirs=[tmp_path / "plugins"])
    loader.registry = fresh_registry
    manifest = PluginManifest.from_dict(
        json.loads((installed / "plugin.json").read_text(encoding="utf-8")),
    )
    await loader.load_plugin(manifest, installed)
    assert (dest / "note.md").read_text(encoding="utf-8") == "v1\n"
    (dest / "note.md").write_text("user\n", encoding="utf-8")

    staging = _write_provision_plugin(
        tmp_path / "staging-prov",
        "prov",
        dest,
        "2.0.0",
        "v2\n",
        boom=True,
    )
    report = await loader.lifecycle.reload("prov", new_source=staging)
    assert not report.ok
    assert (dest / "note.md").read_text(encoding="utf-8") == "user\n"


@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup_fails", [False, True])
async def test_successful_reload_replaces_source(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
    cleanup_fails,
):
    monkeypatch.setattr(
        "qwenpaw.constant.WORKING_DIR",
        tmp_path / "work",
    )
    installed = _write_plugin(tmp_path / "plugins" / "swap", "swap")
    loader = PluginLoader(plugin_dirs=[tmp_path / "plugins"])
    loader.registry = fresh_registry
    manifest = PluginManifest.from_dict(
        json.loads((installed / "plugin.json").read_text(encoding="utf-8")),
    )
    await loader.load_plugin(manifest, installed)
    old_instance = loader.lifecycle.get_instance("swap")
    assert old_instance is not None
    if cleanup_fails:

        def fail_cleanup(_path):
            raise PermissionError("committed backup is busy")

        monkeypatch.setattr("qwenpaw.plugins.loader._remove_dir", fail_cleanup)
    staging = _write_plugin(
        tmp_path / "staging-swap",
        "swap",
        body="api.register_slash_command('ok', lambda c, a: None)",
    )
    report = await loader.lifecycle.reload("swap", new_source=staging)
    assert report.ok
    assert not report.unchanged
    new_instance = loader.lifecycle.get_instance("swap")
    assert new_instance is not None and new_instance is not old_instance
    assert new_instance.generation == old_instance.generation + 1
    assert report.needs_restart is cleanup_fails
    if cleanup_fails:
        assert any("committed backup is busy" in e for e in report.errors)
    assert "register_slash_command" in (installed / "main.py").read_text(
        encoding="utf-8",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_ids", [("default",), ("default", "other")])
@pytest.mark.parametrize("entry", ["reload", "force"])
async def test_memory_in_use_does_not_report_upgrade_success(
    tmp_path,
    fresh_registry,
    monkeypatch,
    agent_ids,
    entry,
):
    from qwenpaw import memory

    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    isolated = MemoryBackendRegistry()
    monkeypatch.setattr(memory, "memory_registry", isolated)
    installed = _write_plugin(
        tmp_path / "plugins" / "memory-upgrade",
        "memory-upgrade",
        body=(
            "api.register_memory_backend(backend_id='selected', "
            "factory=type('Factory', (), {}))"
        ),
    )
    loader = PluginLoader([tmp_path / "plugins"])
    loader.registry = fresh_registry
    manifest = PluginManifest.from_dict(
        json.loads(
            (installed / "plugin.json").read_text(encoding="utf-8"),
        ),
    )
    old_record = await loader.load_plugin(manifest, installed)
    old_instance = loader.lifecycle.get_instance("memory-upgrade")
    fresh_registry.set_workspace_manager(
        SimpleNamespace(
            agents={
                agent_id: SimpleNamespace(
                    agent_id=agent_id,
                    _config=SimpleNamespace(
                        running=SimpleNamespace(
                            memory_manager_backend="selected",
                        ),
                    ),
                )
                for agent_id in agent_ids
            },
        ),
    )
    incoming = _write_plugin(
        tmp_path / "incoming",
        "memory-upgrade",
        version="2.0.0",
    )

    async def unexpected_commit(*_args):
        pytest.fail("rejected update must not finish a commit")

    monkeypatch.setattr(loader, "_finish_committed_reload", unexpected_commit)
    if entry == "force":
        with pytest.raises(RuntimeError) as exc:
            await loader.load_plugin_from_path(incoming, force=True)
        errors = str(exc.value)
    else:
        report = await loader.lifecycle.reload(
            "memory-upgrade",
            new_source=incoming,
        )
        assert not report.ok and report.unchanged
        assert not report.needs_restart
        assert report.generation == old_instance.generation
        errors = "; ".join(report.errors)
    assert all(agent_id in errors for agent_id in agent_ids)
    assert "New version was not enabled" in errors
    assert "previous service is still active" in errors
    assert loader.lifecycle.get_instance("memory-upgrade") is old_instance
    assert loader.get_loaded_plugin("memory-upgrade") is old_record
    assert old_record.status == "active"
    assert old_record.manifest.version == "1.0.0"
    assert not marker_path("memory-upgrade").exists()
    assert (
        json.loads((installed / "plugin.json").read_text())["version"]
        == "1.0.0"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "entry,restore_blocked",
    [("reload", False), ("reload", True), ("force", False)],
)
async def test_cancel_during_completed_swap_restores_old_disk(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
    entry: str,
    restore_blocked: bool,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    plugin_id = "cancel-swap"
    installed = _write_plugin(
        tmp_path / "plugins" / plugin_id,
        plugin_id,
        body="self.version = 'old'",
    )
    staging = _write_plugin(
        tmp_path / "incoming",
        plugin_id,
        body="self.version = 'new'",
        version="2.0.0",
    )
    loader = PluginLoader(plugin_dirs=[installed.parent])
    loader.registry = fresh_registry
    if entry == "reload":
        await loader.load_plugin(
            PluginManifest.from_dict(
                json.loads((installed / "plugin.json").read_text()),
            ),
            installed,
        )
    loop = asyncio.get_running_loop()
    cancelled = threading.Event()
    move = shutil.move
    task = None

    def cancel_reload():
        task.cancel()
        cancelled.set()

    def move_then_cancel(src, dest, *args, **kwargs):
        source = Path(src)
        if restore_blocked and ".bak" in source.name:
            raise PermissionError("plugin restore occupied")
        result = move(src, dest, *args, **kwargs)
        if source.name.endswith(".staging") and Path(dest) == installed:
            loop.call_soon_threadsafe(cancel_reload)
            assert cancelled.wait(
                WAIT_TIMEOUT * 2,
            ), "reload cancellation was not delivered"
        return result

    monkeypatch.setattr(shutil, "move", move_then_cancel)
    operation = (
        loader.lifecycle.reload(plugin_id, new_source=staging)
        if entry == "reload"
        else loader.load_plugin_from_path(staging, force=True)
    )
    task = asyncio.create_task(operation)
    with pytest.raises(asyncio.CancelledError):
        await task
    record = loader.get_loaded_plugin(plugin_id)
    if restore_blocked:
        marker = json.loads(marker_path(plugin_id).read_text())
        assert marker["status"] == "prepared"
        backup = Path(marker["backup_path"])
        assert json.loads((backup / "plugin.json").read_text())["version"] == (
            "1.0.0"
        )
        assert record is None or record.status == "failed"
        instance = loader.lifecycle.get_instance(plugin_id)
        assert "needs_restart" in instance.diagnostics
        assert any(
            "plugin restore occupied" in error
            for error in instance.diagnostics
        )
        with pytest.raises(RuntimeError, match="plugin restore occupied"):
            await loader.lifecycle.activate(plugin_id)
    else:
        assert json.loads((installed / "plugin.json").read_text())[
            "version"
        ] == ("1.0.0")
        if entry == "reload":
            assert record.status == "active"
            assert record.manifest.version == "1.0.0"
            module = sys.modules[plugin_module_name(plugin_id)]
            assert module.plugin.version == "old"
        else:
            assert record is None
        assert not marker_path(plugin_id).exists()
        assert not list(installed.parent.glob(f"{plugin_id}*.bak*"))


@pytest.mark.asyncio
async def test_force_install_keeps_old_when_probe_fails(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr(
        "qwenpaw.constant.WORKING_DIR",
        tmp_path / "work",
    )
    installed = _write_plugin(tmp_path / "plugins" / "facade", "facade")
    loader = PluginLoader(plugin_dirs=[tmp_path / "plugins"])
    loader.registry = fresh_registry
    manifest = PluginManifest.from_dict(
        json.loads((installed / "plugin.json").read_text(encoding="utf-8")),
    )
    await loader.load_plugin(manifest, installed)
    staging = tmp_path / "staging-facade"
    _write_plugin(staging, "facade")
    (staging / "main.py").write_text("def (\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="probe failed"):
        await loader.load_plugin_from_path(staging, force=True)
    assert "facade" in loader.get_all_loaded_plugins()
    assert "class _P" in (installed / "main.py").read_text(encoding="utf-8")
