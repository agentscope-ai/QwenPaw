# -*- coding: utf-8 -*-
# pylint: disable=import-outside-toplevel,redefined-outer-name,too-many-locals
"""Explicit repair must publish validation for the retained source only."""

import shutil
import sys
from types import SimpleNamespace as NS

from fastapi import Request
from packaging.markers import default_environment
import pytest

from catalog_suite import candidate, registry as catalog_registry

from extension_admission_suite import runtime

# Re-export the same decorated fixture under its pytest discovery name.
registry = catalog_registry


async def pending_channel(tmp_path, monkeypatch, key):
    """Use formal passive boot with a disabled, credential-free workspace."""
    from qwenpaw.app.channels.manager import ChannelManager
    from qwenpaw.config.config import Config
    from qwenpaw.plugins.loader import PluginLoader
    from qwenpaw.plugins.workspace_projector import WorkspaceProjector

    source, manifest = candidate(tmp_path / "installed", key)
    config = Config(plugins={key: {"enabled": True}})
    workspace = NS(
        agent_id="unconfigured",
        config=config,
        _config=config,
        channel_manager=ChannelManager([]),
    )
    monkeypatch.setattr("qwenpaw.config.utils.load_config", lambda: config)
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_plugins_dir",
        lambda: source.parent,
    )
    loader = PluginLoader([source.parent], channel_runtime=runtime(None))
    loader.registry.projector = WorkspaceProjector(
        live_workspaces=lambda: [workspace],
    )

    async def forbidden(*args, **kwargs):
        raise AssertionError("Passive boot must not prepare a platform")

    monkeypatch.setattr(loader, "_prepare_channel_candidate", forbidden)
    record = await loader.load_plugin(
        manifest,
        source,
        {"enabled": True},
        activate=False,
    )
    await loader.activate_all_loaded()
    assert record.status == "active" and record.enabled
    assert "channel_validation_pending" in record.diagnostics
    assert "channel_validation_passed" not in record.diagnostics
    assert workspace.channel_manager.channels == []
    return loader, record, workspace


def prepared_snapshot(tmp_path):
    """Supply complete validated transport evidence at the platform seam."""
    from qwenpaw.plugins.execution.dependencies import DependencySnapshot

    site = str(tmp_path / "dependency-site")
    return DependencySnapshot.from_mapping(
        {
            "executable": sys.executable,
            "prefix": sys.prefix,
            "sites": [site],
            "dependency_sites": [site],
            "marker_environment": default_environment(),
            "supported_tags": ["py3-none-any"],
            "distributions": {},
        },
    )


def declaration(loader, row):
    """Read the existing catalog's dependency evidence through its token."""
    uses = loader.registry.dependency_usage.snapshot(
        admission_token=row.dependency_token,
    ).uses
    return next(
        use
        for use in uses
        if use.plugin_id == row.plugin_id and use.origin == "declaration"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["feishu", "dingtalk"])
async def test_active_channel_repair_publishes_validation_without_replacing_catalog(  # noqa: E501
    tmp_path,
    monkeypatch,
    registry,
    key,
):
    """A fresh equivalent description must validate the retained active row."""
    from qwenpaw.app.routers.config import list_channel_schemas
    from qwenpaw.app.routers.plugins import repair_plugin_dependencies

    loader, record, workspace = await pending_channel(
        tmp_path,
        monkeypatch,
        key,
    )
    row = registry.get_channel_catalog_entry(key)
    original_description = record.backend_binding.description
    snapshot = prepared_snapshot(tmp_path)
    assert declaration(loader, row).snapshot is None

    async def get_agent(_request):
        return workspace

    async def prepare(*_args, **_kwargs):
        return NS(snapshot=snapshot)

    monkeypatch.setattr(
        "qwenpaw.app.agent_context.get_agent_for_request",
        get_agent,
    )
    request = Request(
        {"type": "http", "app": NS(state=NS(plugin_loader=loader))},
    )
    before = (await list_channel_schemas(request))[key]
    assert before["availability"] == "validation_pending"
    assert before["repair"]["action"] == "repair"
    monkeypatch.setattr(loader, "_prepare_channel_candidate", prepare)
    response = await repair_plugin_dependencies(key, request)

    assert loader.get_loaded_plugin(key) is record
    assert registry.get_channel_catalog_entry(key) is row
    assert record.backend_binding.description is original_description
    assert response["status"] == "active"
    assert "channel_validation_passed" in response["diagnostics"]
    assert "channel_validation_pending" not in response["diagnostics"]
    assert declaration(loader, row).snapshot == snapshot
    after = (await list_channel_schemas(request))[key]
    assert after["availability"] == "validated"
    assert "repair" not in after
    assert workspace.channel_manager.channels == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["revision", "path", "manifest"])
async def test_other_source_preparation_cannot_validate_retained_channel(
    tmp_path,
    monkeypatch,
    registry,
    change,
):
    """
    A different candidate must not publish evidence for the active source.
    """
    loader, record, _workspace = await pending_channel(
        tmp_path,
        monkeypatch,
        "feishu",
    )
    row = registry.get_channel_catalog_entry("feishu")
    before = declaration(loader, row)
    binding = record.backend_binding
    source = record.source_path
    manifest = record.manifest.model_copy(deep=True)
    if change == "revision":
        (source / "feishu" / "driver.py").write_text("# changed source\n")
    elif change == "path":
        copied = tmp_path / "different-root" / "feishu"
        shutil.copytree(source, copied)
        source = copied
    else:
        manifest = manifest.model_copy(update={"version": "2.0.0"})
    description = binding.backend.describe(source, manifest)
    snapshot = prepared_snapshot(tmp_path)

    async def prepare(*_args, **_kwargs):
        return NS(snapshot=snapshot)

    monkeypatch.setattr(loader, "_prepare_channel_candidate", prepare)
    await binding.backend.prepare(description, allow_install=True, probe=True)
    assert "channel_validation_pending" in record.diagnostics
    assert "channel_validation_passed" not in record.diagnostics
    assert registry.get_channel_catalog_entry("feishu") is row
    assert record.backend_binding is binding
    assert declaration(loader, row) == before


@pytest.mark.asyncio
async def test_failed_repair_preserves_pending_validation_and_dependency_evidence(  # noqa: E501
    tmp_path,
    monkeypatch,
    registry,
):
    """
    A probe error must leave the retained source's status and evidence
    intact.
    """
    loader, record, _workspace = await pending_channel(
        tmp_path,
        monkeypatch,
        "feishu",
    )
    row = registry.get_channel_catalog_entry("feishu")
    before = declaration(loader, row)

    async def failed_probe(*args, **kwargs):
        raise RuntimeError("CHANNEL_IMPORT_FAILED")

    monkeypatch.setattr(loader, "_prepare_channel_candidate", failed_probe)
    with pytest.raises(RuntimeError, match="CHANNEL_IMPORT_FAILED"):
        await loader.repair_dependencies("feishu")
    assert loader.get_loaded_plugin("feishu") is record
    assert "channel_validation_pending" in record.diagnostics
    assert "channel_validation_passed" not in record.diagnostics
    assert declaration(loader, row) == before
