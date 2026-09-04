# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Probe import, reload rollback, and provision migration."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.plugins.architecture import PluginManifest
from qwenpaw.plugins.lifecycle import PluginInstance, UnloadMode
from qwenpaw.plugins.loader import PluginLoader
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
from qwenpaw.plugins.registry import PluginRegistry
from qwenpaw.plugins.updates import (
    recover_interrupted_updates,
    write_updating_marker,
)
from qwenpaw.plugins.workspace_projector import WorkspaceProjector
from qwenpaw.runtime.slash_command_registry import SlashCommandRegistry


@pytest.fixture()
def fresh_registry():
    old = PluginRegistry._instance
    PluginRegistry._instance = None
    registry = PluginRegistry()
    yield registry
    PluginRegistry._instance = old


def _write_plugin(
    root: Path,
    plugin_id: str,
    *,
    body: str = "pass",
    extra_py: str | None = None,
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
    if extra_py is not None:
        (root / "helper.py").write_text(extra_py, encoding="utf-8")
    return root


@pytest.mark.asyncio
async def test_syntax_error_reload_keeps_old(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
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
    (broken / "main.py").write_text("def (\n", encoding="utf-8")

    report = await loader.lifecycle.reload(
        "keep-old",
        new_source=broken,
    )
    assert report.unchanged
    assert not report.ok
    assert "keep-old" in loader.get_all_loaded_plugins()
    assert "ping" in workspace.plugins.slash_command_registry.names()
    assert (
        (installed / "main.py")
        .read_text(encoding="utf-8")
        .count(
            "register_slash_command",
        )
    )


@pytest.mark.asyncio
async def test_module_level_probe_failure_keeps_old(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr(
        "qwenpaw.constant.WORKING_DIR",
        tmp_path / "work",
    )
    installed = _write_plugin(tmp_path / "plugins" / "boom", "boom")
    loader = PluginLoader(plugin_dirs=[tmp_path / "plugins"])
    loader.registry = fresh_registry
    manifest = PluginManifest.from_dict(
        json.loads((installed / "plugin.json").read_text(encoding="utf-8")),
    )
    await loader.load_plugin(manifest, installed)

    staging = tmp_path / "staging-boom"
    _write_plugin(staging, "boom")
    (staging / "main.py").write_text(
        "raise RuntimeError('module boom')\n",
        encoding="utf-8",
    )
    report = await loader.lifecycle.reload("boom", new_source=staging)
    assert report.unchanged
    assert "boom" in loader.get_all_loaded_plugins()
    assert "boom" in fresh_registry.get_all_plugin_manifests()


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
async def test_successful_reload_replaces_source(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
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
    staging = _write_plugin(
        tmp_path / "staging-swap",
        "swap",
        body="api.register_slash_command('ok', lambda c, a: None)",
    )
    report = await loader.lifecycle.reload("swap", new_source=staging)
    assert report.ok
    assert not report.unchanged
    assert "register_slash_command" in (installed / "main.py").read_text(
        encoding="utf-8",
    )


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
