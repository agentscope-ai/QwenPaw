# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,unused-argument
"""C6 host ownership and passive boot contracts without vendor imports."""

import importlib.abc
from pathlib import Path
import sys
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from catalog_suite import candidate

pytest_plugins = ["catalog_suite"]

ROOT = Path(__file__).resolve().parents[3]


def test_c6_default_registry_never_attempts_legacy_platform_imports(registry):
    from qwenpaw.app.channels.registry import (
        clear_builtin_channel_cache,
        get_channel_registry,
    )

    attempts = []

    class RecordLegacyImports(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.startswith(
                (
                    "qwenpaw.app.channels.feishu",
                    "qwenpaw.app.channels.dingtalk",
                ),
            ):
                attempts.append(fullname)
                raise ImportError("Legacy channel must never be resolved")

    guard = RecordLegacyImports()
    sys.meta_path.insert(0, guard)
    try:
        clear_builtin_channel_cache()
        channels = get_channel_registry()
    finally:
        sys.meta_path.remove(guard)
        clear_builtin_channel_cache()
    assert "console" in channels
    assert not attempts
    assert not {"feishu", "dingtalk"}.intersection(channels)


def test_c6_official_ownership_is_permanent_without_runtime(registry):
    from qwenpaw.app.channels.registry import (
        BUILTIN_CHANNEL_KEYS,
        selected_process_channels,
    )

    assert {"feishu", "dingtalk"} <= selected_process_channels()
    assert not {"feishu", "dingtalk"}.intersection(BUILTIN_CHANNEL_KEYS)
    assert "console" in BUILTIN_CHANNEL_KEYS


def c6_loader(tmp_path, workspaces=None):
    from qwenpaw.plugins.channel_adapter import ChannelRuntimeSettings
    from qwenpaw.plugins.loader import PluginLoader
    from qwenpaw.plugins.workspace_projector import WorkspaceProjector

    source, manifest = candidate(tmp_path / "installed")
    loader = PluginLoader(
        [source.parent],
        channel_runtime=ChannelRuntimeSettings(
            python_executable=sys.executable,
            support_root=ROOT / "src",
            qwenpaw_version="2.2.2b4",
            selected_channels=frozenset({"feishu", "dingtalk"}),
        ),
    )
    loader.registry.projector = WorkspaceProjector(
        live_workspaces=lambda: workspaces or [],
    )
    return loader, source, manifest


@pytest.mark.asyncio
@pytest.mark.parametrize("disabled_workspace", [False, True])
async def test_c6_passive_boot_arms_hooks_without_unused_sdk_probe(
    tmp_path,
    registry,
    monkeypatch,
    disabled_workspace,
):
    manager = NS(start_one=AsyncMock(return_value=NS()))
    workspace = NS(
        agent_id="c6-later",
        channel_manager=manager,
        _config=NS(channels=NS(feishu=NS(enabled=False))),
    )
    workspaces = [workspace] if disabled_workspace else []
    loader, source, manifest = c6_loader(tmp_path, workspaces)
    probes = []

    async def observe_probe(*args, **kwargs):
        probes.append((args, kwargs))

    monkeypatch.setattr(loader, "_prepare_channel_candidate", observe_probe)
    record = await loader.load_plugin(
        manifest,
        source,
        {"enabled": True},
        activate=False,
    )
    await loader.activate_all_loaded()
    assert not probes
    instance = loader.lifecycle.get_instance("feishu")
    assert instance.activated, "Later workspace enables still need armed hooks"
    assert record.status not in {"running", "validated"}
    assert loader.registry.get_channel_catalog_entry("feishu") is not None
    manager.start_one.assert_not_awaited()
    if not disabled_workspace:
        workspaces.append(workspace)
    workspace._config.channels.feishu.enabled = True
    await loader.registry.projector.project("channel", "feishu", "feishu")
    manager.start_one.assert_awaited_once()


@pytest.mark.asyncio
async def test_c6_explicit_validation_may_probe_without_workspace(
    tmp_path,
    registry,
    monkeypatch,
):
    loader, source, manifest = c6_loader(tmp_path)
    probes = []

    async def observe_probe(*args, **kwargs):
        probes.append((args, kwargs))

    monkeypatch.setattr(loader, "_prepare_channel_candidate", observe_probe)
    await loader.load_plugin(
        manifest,
        source,
        {"enabled": True},
        activate=True,
    )
    assert probes, "Explicit activation must validate before commit"


@pytest.mark.parametrize("key", ["feishu", "dingtalk"])
def test_c6_descriptor_fields_are_frontend_widgets(tmp_path, registry, key):
    from catalog_suite import describe

    source, manifest = candidate(tmp_path, key)
    row = registry.register_channel_descriptor(key, describe(source, manifest))
    fields = {field["name"]: field for field in row.config_fields}
    assert fields["streaming_enabled"]["type"] == "switch"
    secret = "app_secret" if key == "feishu" else "client_secret"
    assert fields[secret]["type"] == "password"
    assert fields["media_dir"]["type"] == "text"
    assert fields["media_dir"]["default"] is None


@pytest.mark.asyncio
async def test_c6_disabled_discovery_retains_static_catalog(
    tmp_path,
    registry,
    monkeypatch,
):
    loader, _source, _manifest = c6_loader(tmp_path)

    async def forbidden_probe(*args, **kwargs):
        raise AssertionError("Disabled discovery probed a vendor")

    monkeypatch.setattr(loader, "_prepare_channel_candidate", forbidden_probe)
    await loader.load_all_plugins(
        configs={"feishu": {"enabled": False}},
        types=["channel"],
        activate=False,
    )
    row = loader.registry.get_channel_catalog_entry("feishu")
    assert row is not None
    assert row.global_enabled is False
    assert loader.get_loaded_plugin("feishu").enabled is False


@pytest.mark.parametrize(
    "name,kind,default",
    [("access_tokens", "array", []), ("secret_map", "object", {})],
)
def test_c6_structured_secret_names_keep_json_widget_and_type(
    name,
    kind,
    default,
):
    from qwenpaw.app.channels.catalog import config_fields

    fields = config_fields(
        {
            "type": "object",
            "required": [name],
            "properties": {
                name: {"type": kind, "default": default},
                "api_token": {"type": "string"},
            },
        },
    )
    structured, scalar = fields
    assert structured["type"] == "json"
    assert structured["json_type"] == kind
    assert structured["default"] == default and structured["required"] is True
    assert scalar["type"] == "password"
