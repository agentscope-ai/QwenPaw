# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Probe import, reload rollback, and provision migration."""

from __future__ import annotations

import json
import importlib.util
import os
import py_compile
import shutil
import sys
from pathlib import Path

import pytest

from qwenpaw.plugins.architecture import PluginManifest
from qwenpaw.plugins.lifecycle import UnloadMode
from qwenpaw.plugins.loader import PluginLoader
from qwenpaw.plugins.provision import load_inventory, provision_files


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
