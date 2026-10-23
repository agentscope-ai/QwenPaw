# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,unused-argument
# pylint: disable=missing-function-docstring,duplicate-code
"""Review regressions for descriptor reload and destination install gates."""

import json
from types import SimpleNamespace as NS

import pytest

from catalog_suite import (
    candidate,
    file_snapshot,
    manifest_data,
    prohibit_loader_side_effects,
    registry as _registry_fixture,
)
from qwenpaw.plugins.architecture import PluginManifest, PluginRecord

registry = _registry_fixture


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit_path", [False, True])
async def test_in_place_reload_reads_disk_descriptor_before_effects(
    tmp_path,
    registry,
    monkeypatch,
    explicit_path,
):
    from qwenpaw.plugins.loader import PluginLoader

    installed, _descriptor_manifest = candidate(tmp_path / "installed")
    old_data = manifest_data()
    old_data["entry"] = {"backend": "plugin.py"}
    old_manifest = PluginManifest.from_dict(old_data)
    (installed / "plugin.py").write_text("old Python entry bytes")
    loader = PluginLoader([installed.parent])
    loader.registry = registry
    record = PluginRecord(old_manifest, installed, True, instance=NS())
    loader._loaded_plugins["feishu"] = record
    instance = loader.lifecycle.ensure_instance("feishu")
    instance.config = {"app_id": "saved"}
    before = file_snapshot(tmp_path)
    manifest_before = record.manifest.model_dump()
    prohibit_loader_side_effects(loader, monkeypatch)

    def forbidden(*args, **kwargs):
        raise AssertionError("in-place descriptor crossed reload boundary")

    monkeypatch.setattr("qwenpaw.plugins.loader._probe_incoming", forbidden)
    monkeypatch.setattr(loader.lifecycle, "_unload_unlocked", forbidden)
    result = await loader.reload_plugin_unlocked(
        "feishu",
        **({"new_source": installed} if explicit_path else {}),
    )
    assert not result.ok and result.unchanged
    assert any(
        "channel_runtime_not_integrated" in error for error in result.errors
    )
    assert loader.get_loaded_plugin("feishu") is record
    assert record.manifest.model_dump() == manifest_before
    assert instance.config == {"app_id": "saved"}
    assert file_snapshot(tmp_path) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_force_python_install_preserves_unloaded_descriptor_destination(
    tmp_path,
    registry,
    monkeypatch,
    enabled,
):
    from qwenpaw.plugins.loader import PluginLoader

    installed, _manifest = candidate(tmp_path / "installed")
    incoming = tmp_path / "incoming" / "feishu"
    incoming.mkdir(parents=True)
    data = manifest_data()
    data["entry"] = {"backend": "plugin.py"}
    (incoming / "plugin.json").write_text(json.dumps(data))
    (incoming / "plugin.py").write_text("incoming Python bytes")
    saved = {"enabled": enabled, "app_id": "saved"}
    settings = NS(plugins={"feishu": saved})
    settings_before = dict(saved)
    (tmp_path / "settings.json").write_text(json.dumps(settings.plugins))
    loader = PluginLoader([installed.parent])
    loader.registry = registry
    assert loader.get_loaded_plugin("feishu") is None
    before = file_snapshot(tmp_path)
    monkeypatch.setattr("qwenpaw.config.utils.load_config", lambda: settings)
    prohibit_loader_side_effects(loader, monkeypatch)

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "descriptor destination crossed mutation boundary",
        )

    monkeypatch.setattr(loader, "_swap_plugin_dir", forbidden)
    monkeypatch.setattr(
        loader,
        "_recover_or_refuse_prepared_update",
        forbidden,
    )
    monkeypatch.setattr(
        "qwenpaw.plugins.settings.persist_plugin_settings",
        forbidden,
    )
    monkeypatch.setattr("qwenpaw.config.utils.save_config", forbidden)
    with pytest.raises(RuntimeError, match="channel_runtime_not_integrated"):
        await loader.load_plugin_from_path(
            incoming,
            force=True,
            install_dir=installed.parent,
        )
    assert file_snapshot(tmp_path) == before
    assert saved == settings_before
    assert loader.get_loaded_plugin("feishu") is None
    assert registry.get_channel_catalog() == {}


@pytest.mark.asyncio
async def test_descriptor_refusal_preserves_matching_prepared_pawport_target(
    tmp_path,
    registry,
    monkeypatch,
):
    from qwenpaw.plugins.loader import PluginLoader

    installed, _manifest = candidate(tmp_path / "installed")
    owner = {"owner": "review", "provider": "fixture", "source_id": "one"}
    (installed / ".qwenpaw-pawport.json").write_text(
        json.dumps({**owner, "state": "prepared"}),
    )
    incoming = tmp_path / "incoming" / "feishu"
    incoming.mkdir(parents=True)
    data = manifest_data()
    data["entry"] = {"backend": "plugin.py"}
    (incoming / "plugin.json").write_text(json.dumps(data))
    (incoming / "plugin.py").write_text("incoming Python bytes")
    loader = PluginLoader([installed.parent])
    loader.registry = registry
    before = file_snapshot(tmp_path)
    cleanup_calls = []
    real_cleanup = loader._remove_incomplete_pawport_plugin

    def tracked_cleanup(*args, **kwargs):
        cleanup_calls.append(args)
        return real_cleanup(*args, **kwargs)

    monkeypatch.setattr(
        loader,
        "_remove_incomplete_pawport_plugin",
        tracked_cleanup,
    )
    with pytest.raises(RuntimeError, match="channel_runtime_not_integrated"):
        await loader.load_plugin_from_path(
            incoming,
            force=True,
            install_dir=installed.parent,
            pawport_owner=owner,
            recover_incomplete=True,
        )
    assert not cleanup_calls
    assert file_snapshot(tmp_path) == before
    assert loader.get_loaded_plugin("feishu") is None
