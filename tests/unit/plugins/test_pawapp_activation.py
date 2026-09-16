# -*- coding: utf-8 -*-
"""Versioned PawApps install statically and execute only on activation."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from qwenpaw.app.routers import plugins as plugin_routes
from qwenpaw.config import utils as config_utils
from qwenpaw.plugins.loader import PluginLoader
from qwenpaw.plugins.registry import PluginRegistry


@pytest.fixture
def fresh_registry():
    previous = PluginRegistry._instance
    PluginRegistry._instance = None
    registry = PluginRegistry()
    yield registry
    PluginRegistry._instance = previous


def write_pawapp(source: Path, sentinel: Path) -> None:
    source.mkdir(parents=True)
    (source / "plugin.json").write_text(
        json.dumps(
            {
                "id": "review-app",
                "name": "Review App",
                "version": "1.0.0",
                "type": "app",
                "entry": {
                    "backend": "plugin.py",
                    "frontend": "index.js",
                },
                "qwenpaw_version": {"min": "0.1.0", "max": "99.0.0"},
                "pawapp": {"schema_version": 1, "runtime": {}},
                "meta": {"pawapp": {"entry_page": "/apps/review-app"}},
            },
        ),
        encoding="utf-8",
    )
    (source / "index.js").write_text("export default true", encoding="utf-8")
    (source / "plugin.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(sentinel)!r}).write_text('executed')\n"
        "class Plugin:\n"
        "    def register(self, api):\n"
        "        del api\n"
        "plugin = Plugin()\n",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_install_is_static_until_explicit_activation(
    tmp_path,
    fresh_registry,
    monkeypatch,
):
    source = tmp_path / "source"
    installed = tmp_path / "installed"
    sentinel = tmp_path / "executed"
    write_pawapp(source, sentinel)
    loader = PluginLoader(
        [installed],
        activation_dir=tmp_path / "activations",
    )
    loader.registry = fresh_registry
    dependency_install = AsyncMock()
    loader._ensure_dependencies_installed = dependency_install

    record = await loader.load_plugin_from_path(
        source,
        install_dir=installed,
        defer_pawapp_activation=True,
    )

    assert record.enabled is False
    assert record.diagnostics == ["installed_not_activated"]
    assert loader.get_loaded_plugin("review-app") is None
    assert not sentinel.exists()
    dependency_install.assert_not_awaited()

    monkeypatch.setattr(config_utils, "get_plugins_dir", lambda: installed)
    assert plugin_routes._list_plugins_with_runtime(loader) == [
        {
            "id": "review-app",
            "name": "Review App",
            "version": "1.0.0",
            "description": "",
            "author": "",
            "enabled": False,
            "loaded": False,
            "requires_activation": True,
            "activation_status": "installed",
            "plugin_type": "app",
            "frontend_entry": "index.js",
        },
    ]
    assert not sentinel.exists()

    active = await loader.activate_plugin("review-app")
    assert active.enabled is True
    assert sentinel.read_text() == "executed"
    dependency_install.assert_awaited_once()


@pytest.mark.asyncio
async def test_activation_marker_controls_startup_and_reinstall(
    tmp_path,
    fresh_registry,
):
    source = tmp_path / "source"
    installed = tmp_path / "installed"
    sentinel = tmp_path / "executed"
    activation_dir = tmp_path / "activations"
    write_pawapp(source, sentinel)
    loader = PluginLoader([installed], activation_dir=activation_dir)
    loader.registry = fresh_registry
    record = await loader.load_plugin_from_path(
        source,
        install_dir=installed,
        defer_pawapp_activation=True,
    )

    await loader.load_all_plugins()
    assert not sentinel.exists()
    assert loader.get_loaded_plugin("review-app") is None

    loader.mark_plugin_activated(record.manifest)
    assert loader.is_plugin_activated(record.manifest)
    await loader.load_all_plugins()
    assert sentinel.exists()

    await loader.unload_plugin("review-app", delete_files=False)
    sentinel.unlink()
    await loader.load_plugin_from_path(
        source,
        install_dir=installed,
        force=True,
        defer_pawapp_activation=True,
    )
    assert not loader.is_plugin_activated(record.manifest)
    assert not sentinel.exists()


@pytest.mark.asyncio
async def test_authenticated_activation_route_marks_success(
    tmp_path,
    fresh_registry,
    monkeypatch,
):
    source = tmp_path / "source"
    installed = tmp_path / "installed"
    sentinel = tmp_path / "executed"
    write_pawapp(source, sentinel)
    loader = PluginLoader(
        [installed],
        activation_dir=tmp_path / "activations",
    )
    loader.registry = fresh_registry
    record = await loader.load_plugin_from_path(
        source,
        install_dir=installed,
        defer_pawapp_activation=True,
    )
    finish = AsyncMock()
    monkeypatch.setattr(
        plugin_routes,
        "_finish_plugin_install_after_load",
        finish,
    )
    monkeypatch.setattr(
        config_utils,
        "load_config",
        lambda _path: SimpleNamespace(plugins={}),
    )
    monkeypatch.setattr(config_utils, "get_config_path", lambda: tmp_path)
    request = Request(
        {
            "type": "http",
            "app": SimpleNamespace(
                state=SimpleNamespace(plugin_loader=loader),
            ),
        },
    )

    response = await plugin_routes.activate_plugin("review-app", request)

    assert response == {
        "id": "review-app",
        "loaded": True,
        "status": "active",
    }
    finish.assert_awaited_once()
    assert loader.is_plugin_activated(record.manifest)
    assert sentinel.exists()


@pytest.mark.asyncio
async def test_activation_failure_rolls_back_without_marker(
    tmp_path,
    fresh_registry,
    monkeypatch,
):
    source = tmp_path / "source"
    installed = tmp_path / "installed"
    sentinel = tmp_path / "executed"
    write_pawapp(source, sentinel)
    loader = PluginLoader(
        [installed],
        activation_dir=tmp_path / "activations",
    )
    loader.registry = fresh_registry
    record = await loader.load_plugin_from_path(
        source,
        install_dir=installed,
        defer_pawapp_activation=True,
    )
    monkeypatch.setattr(
        plugin_routes,
        "_finish_plugin_install_after_load",
        AsyncMock(side_effect=RuntimeError("post-load failed")),
    )
    monkeypatch.setattr(
        config_utils,
        "load_config",
        lambda _path: SimpleNamespace(plugins={}),
    )
    monkeypatch.setattr(config_utils, "get_config_path", lambda: tmp_path)
    request = Request(
        {
            "type": "http",
            "app": SimpleNamespace(
                state=SimpleNamespace(plugin_loader=loader),
            ),
        },
    )

    with pytest.raises(HTTPException) as caught:
        await plugin_routes.activate_plugin("review-app", request)

    assert caught.value.status_code == 400
    assert loader.get_loaded_plugin("review-app") is None
    assert not loader.is_plugin_activated(record.manifest)
