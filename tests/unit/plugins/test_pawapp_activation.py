# -*- coding: utf-8 -*-
"""Versioned PawApps install statically and execute only on activation."""
# pylint: disable=protected-access,redefined-outer-name

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


def write_configured_pawapp(source: Path) -> None:
    source.mkdir(parents=True)
    (source / "plugin.json").write_text(
        json.dumps(
            {
                "id": "configured-app",
                "name": "Configured App",
                "version": "1.0.0",
                "type": "app",
                "entry": {"backend": "plugin.py", "frontend": "index.js"},
                "qwenpaw_version": {"min": "0.1.0", "max": "99.0.0"},
                "pawapp": {
                    "schema_version": 1,
                    "configuration": {
                        "version": 1,
                        "setup_entries": [
                            {
                                "id": "models",
                                "entry_ref": "configured.models",
                                "focus": "primary-model",
                                "presentations": ["app_entry"],
                            },
                        ],
                    },
                },
                "meta": {"pawapp": {"entry_page": "/apps/configured-app"}},
            },
        ),
        encoding="utf-8",
    )
    (source / "index.js").write_text("export default true", encoding="utf-8")
    (source / "plugin.py").write_text(
        "from qwenpaw.pawapp import (PawApp, SetupEntryDescriptor, "
        "SetupEntryRegistration, SetupOpenAction)\n"
        "app = PawApp('Configured App', app_id='configured-app')\n"
        "async def open_setup(request):\n"
        "    return SetupOpenAction(app_id='configured-app', "
        "request_id=request.request_id, entry_id=request.entry_id, "
        "presentation=request.presentation, path='/apps/configured-app')\n"
        "app.setup_entry(SetupEntryRegistration("
        "descriptor=SetupEntryDescriptor(id='models', "
        "entry_ref='configured.models', focus='primary-model', "
        "presentations=('app_entry',)), opener=open_setup))\n",
        encoding="utf-8",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("offline", [False, True])
async def test_install_is_static_until_explicit_activation(
    tmp_path,
    fresh_registry,
    monkeypatch,
    offline,
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
    dependency_install = AsyncMock(
        wraps=loader._ensure_dependencies_installed,
    )
    loader._ensure_dependencies_installed = dependency_install

    if offline:
        record = await loader.install_plugin_files(source)
    else:
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
async def test_loader_preserves_typed_pawapp_setup_manifest(
    tmp_path,
    fresh_registry,
):
    source = tmp_path / "configured-source"
    write_configured_pawapp(source)
    loader = PluginLoader([tmp_path])
    loader.registry = fresh_registry

    record = await loader.load_plugin_from_path(source)

    assert record.enabled is True
    assert (
        "configured-app",
        "models",
    ) in fresh_registry.get_pawapp_setup_entries()


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
    finish = AsyncMock(wraps=loader.run_plugin_startup_hooks)
    monkeypatch.setattr(
        loader,
        "run_plugin_startup_hooks",
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
        loader,
        "run_plugin_startup_hooks",
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

    assert caught.value.status_code == 409
    failed = loader.get_loaded_plugin("review-app")
    assert failed.status == "failed"
    assert failed.enabled is False
    assert fresh_registry.get_plugin_manifest("review-app") is None
    assert not loader.is_plugin_activated(record.manifest)


@pytest.mark.asyncio
async def test_activation_starts_once_and_force_reinstall_stays_inert(
    tmp_path,
    fresh_registry,
):
    source = tmp_path / "source"
    installed = tmp_path / "installed"
    sentinel = tmp_path / "executed"
    starts = tmp_path / "starts"
    write_pawapp(source, sentinel)
    (source / "plugin.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(sentinel)!r}).write_text('executed')\n"
        "def start():\n"
        f"    path = Path({str(starts)!r})\n"
        "    previous = path.read_text() if path.exists() else ''\n"
        "    path.write_text(previous + 'x')\n"
        "class Plugin:\n"
        "    def register(self, api):\n"
        "        api.register_startup_hook('start', start)\n"
        "plugin = Plugin()\n",
    )
    loader = PluginLoader([installed], activation_dir=tmp_path / "activations")
    loader.registry = fresh_registry
    await loader.load_plugin_from_path(source, defer_pawapp_activation=True)
    first = await loader.activate_plugin("review-app")
    second = await loader.activate_plugin("review-app")
    assert first is second
    assert starts.read_text() == "x"
    sentinel.unlink()

    replacement = await loader.load_plugin_from_path(
        source,
        force=True,
        defer_pawapp_activation=True,
    )
    assert replacement.status == "inactive"
    assert loader.get_loaded_plugin("review-app") is None
    assert not loader.is_plugin_activated(replacement.manifest)
    assert not sentinel.exists()
    assert starts.read_text() == "x"

    await loader.activate_plugin("review-app")
    assert starts.read_text() == "xx"
    await loader.unload_plugin("review-app", delete_files=False)
    await loader.unload_plugin("review-app", delete_files=True)
    assert not loader.is_plugin_activated(replacement.manifest)


@pytest.mark.asyncio
async def test_setup_contracts_survive_config_reregistration(
    tmp_path,
    fresh_registry,
):
    source = tmp_path / "configured-source"
    write_configured_pawapp(source)
    loader = PluginLoader([tmp_path / "installed"])
    loader.registry = fresh_registry
    record = await loader.load_plugin_from_path(source)
    assert record.status == "active"
    key = ("configured-app", "models")
    assert key in fresh_registry.get_pawapp_setup_entries()

    await loader.lifecycle.update_config("configured-app", {"example": True})
    assert loader.get_loaded_plugin("configured-app").status == "active"
    assert list(fresh_registry.get_pawapp_setup_entries()) == [key]
    await loader.unload_plugin("configured-app", delete_files=False)
    assert fresh_registry.get_pawapp_setup_entries() == {}


def test_optional_sdk_field_preserves_existing_activation_receipt(tmp_path):
    import hashlib

    source = tmp_path / "source"
    write_pawapp(source, tmp_path / "executed")
    loader = PluginLoader([tmp_path], activation_dir=tmp_path / "activations")
    _, manifest = loader._read_source_manifest(source)
    previous_payload = manifest.model_dump(mode="json")
    previous_payload.pop("sdk")
    digest = hashlib.sha256(
        json.dumps(
            previous_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8"),
    ).hexdigest()
    loader.activation_dir.mkdir()
    loader._activation_path(manifest.id).write_text(
        json.dumps(
            {"plugin_id": manifest.id, "manifest_digest": f"sha256:{digest}"},
        ),
    )
    assert loader.is_plugin_activated(manifest)
