# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Config rebuild and enabled flag."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.plugins.architecture import PluginManifest
from qwenpaw.plugins.lifecycle import UnloadMode
from qwenpaw.plugins.loader import PluginLoader
from qwenpaw.plugins.registry import PluginRegistry
from qwenpaw.plugins.settings import (
    is_plugin_enabled,
    runtime_config,
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
