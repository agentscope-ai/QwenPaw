# -*- coding: utf-8 -*-
"""Finite C6 offline policy/resource/A-publication an
d trusted runtime tests."""

# pylint: disable=protected-access,redefined-outer-name,unused-argument

import hashlib
import json
import shutil
import sys
from types import SimpleNamespace as NS
import zipfile

import pytest

from c6_artifacts import ROOT


def digest(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def offline(tmp_path, monkeypatch):
    from qwenpaw.plugins import official_channels as official
    from qwenpaw.plugins.loader import PluginLoader
    from qwenpaw.plugins.registry import PluginRegistry
    from qwenpaw.plugins.workspace_projector import WorkspaceProjector
    from qwenpaw.plugins.channel_bootstrap import (
        resolve_default_channel_runtime,
    )

    previous = PluginRegistry._instance
    PluginRegistry._instance = None
    config_path = tmp_path / "config.json"
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "host")
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_config_path",
        lambda: config_path,
    )
    monkeypatch.delenv("QWENPAW_CHANNEL_PRESET", raising=False)
    monkeypatch.delenv("QWENPAW_CHANNEL_RUNTIME_MANIFEST", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    resources = tmp_path / "resources"
    resources.mkdir()
    monkeypatch.setattr(official, "_resource_root", lambda: resources)
    runtime = resolve_default_channel_runtime()
    loader = PluginLoader([tmp_path / "host/plugins"], channel_runtime=runtime)
    loader.registry.projector = WorkspaceProjector(live_workspaces=lambda: [])
    config_path.write_text("{}")
    case = NS(
        loader=loader,
        official=official,
        config_path=config_path,
        resources=resources,
        runtime=runtime,
        root=tmp_path,
    )
    try:
        yield case
    finally:
        PluginRegistry._instance = previous


def bundle(case):
    """Construct real fixture ZIP bytes with exact C7 index v1 identity."""
    from qwenpaw.__version__ import __version__
    from qwenpaw.plugins.official_channel_catalog import OFFICIAL_CHANNELS

    rows = []
    for official in sorted(
        OFFICIAL_CHANNELS, key=lambda row: row["plugin_id"]
    ):
        key = official["plugin_id"]
        source = ROOT / "plugins/channel" / official["source_dir"]
        manifest = json.loads((source / "plugin.json").read_text())
        filename = key + "-" + manifest["version"] + ".zip"
        archive = case.resources / filename
        with zipfile.ZipFile(archive, "w") as zipped:
            for path in sorted(source.rglob("*")):
                if path.is_file() and "__pycache__" not in path.parts:
                    zipped.write(
                        path,
                        key + "/" + path.relative_to(source).as_posix(),
                    )
        rows.append(
            {
                "plugin_id": key,
                "version": manifest["version"],
                "filename": filename,
                "sha256": digest(archive.read_bytes()),
                "descriptor_sha256": digest(
                    (source / "channel.json").read_bytes(),
                ),
                "requirements_sha256": digest(
                    (source / "requirements.txt").read_bytes(),
                ),
                "qwenpaw_version": manifest.get("qwenpaw_version"),
            },
        )
    (case.resources / "index.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "host_version": __version__,
                "plugins": rows,
            },
        ),
    )


def save_raw(case, data):
    case.config_path.write_text(json.dumps(data))


def loaded():
    from qwenpaw.config.utils import load_config

    return load_config()


@pytest.mark.asyncio
async def test_c6_full_preset_uses_A_offline_seed_without_probe(
    offline,
    monkeypatch,
):
    bundle(offline)
    save_raw(
        offline,
        {
            "channel_plugin_state": {"version": 1, "preset": "channels-full"},
            "plugins": {"feishu": {"enabled": False}},
        },
    )

    async def forbidden(*args, **kwargs):
        raise AssertionError(
            "Passive source publication attempted SDK validation",
        )

    monkeypatch.setattr(
        offline.loader,
        "_prepare_channel_candidate",
        forbidden,
    )
    monkeypatch.setattr(
        offline.loader,
        "_ensure_dependencies_installed",
        forbidden,
    )
    assert (
        await offline.official.provision_bundled_channels(offline.loader) == {}
    )
    for key in ("feishu", "dingtalk"):
        source = offline.loader.find_installed_plugin_dir(key)
        assert source is not None and (source / "channel.json").is_file()
        row = offline.loader.registry.get_channel_catalog_entry(key)
        assert row is not None
        record = offline.loader.get_loaded_plugin(key)
        assert record.status not in {"active", "validated", "running"}
    assert (
        offline.loader.registry.get_channel_catalog_entry(
            "feishu",
        ).global_enabled
        is False
    )
    assert loaded().plugins["feishu"]["enabled"] is False


@pytest.mark.asyncio
async def test_c6_legacy_capture_preserves_workspace_and_missing_file(offline):
    bundle(offline)
    workspace = offline.root / "saved-workspace"
    workspace.mkdir()
    raw = {
        "channels": {
            "feishu": {
                "enabled": True,
                "app_id": "cli_old",
                "app_secret": "test-only",
                "domain": "lark",
            },
        },
    }
    saved = workspace / "agent.json"
    saved.write_text(json.dumps(raw))
    original = saved.read_bytes()
    missing = offline.root / "missing-workspace"
    save_raw(
        offline,
        {
            "agents": {
                "profiles": {
                    "old": {"name": "old", "workspace_dir": str(workspace)},
                    "missing": {
                        "name": "missing",
                        "workspace_dir": str(missing),
                    },
                },
            },
            "plugins": {"feishu": {"enabled": False}},
        },
    )
    assert (
        await offline.official.provision_bundled_channels(offline.loader) == {}
    )
    assert offline.loader.find_installed_plugin_dir("feishu") is not None
    assert offline.loader.find_installed_plugin_dir("dingtalk") is None
    assert (
        saved.read_bytes() == original
        and not (missing / "agent.json").exists()
    )
    state = loaded().channel_plugin_state
    assert (
        state.version == 1
        and state.preset == "light"
        and state.legacy_pending == []
    )
    assert loaded().plugins["feishu"]["enabled"] is False


@pytest.mark.asyncio
async def test_c6_missing_resource_keeps_finite_legacy_pending_across_retry(
    offline,
):
    save_raw(
        offline,
        {
            "channels": {
                "dingtalk": {
                    "enabled": True,
                    "client_id": "old",
                    "client_secret": "test-only",
                },
            },
        },
    )
    errors = await offline.official.provision_bundled_channels(offline.loader)
    assert set(errors) == {"dingtalk"}
    assert loaded().channel_plugin_state.legacy_pending == ["dingtalk"]
    bundle(offline)
    assert (
        await offline.official.provision_bundled_channels(offline.loader) == {}
    )
    assert loaded().channel_plugin_state.legacy_pending == []


@pytest.mark.asyncio
async def test_c6_new_light_does_not_capture_future_enables(offline):
    assert (
        await offline.official.provision_bundled_channels(offline.loader) == {}
    )
    root = loaded()
    assert root.channel_plugin_state.version == 1
    root.channels.feishu.enabled = True
    from qwenpaw.config.utils import save_config

    save_config(root)
    bundle(offline)
    assert (
        await offline.official.provision_bundled_channels(offline.loader) == {}
    )
    assert offline.loader.find_installed_plugin_dir("feishu") is None


@pytest.mark.asyncio
async def test_c6_existing_source_is_never_replaced_by_preset(offline):
    bundle(offline)
    existing = offline.root / "host/plugins/feishu"
    shutil.copytree(ROOT / "plugins/channel/feishu", existing)
    marker = existing / "user-marker"
    marker.write_text("preserve user source")
    save_raw(
        offline,
        {
            "channel_plugin_state": {
                "version": 1,
                "preset": "channels-full",
                "legacy_pending": ["feishu"],
            },
        },
    )
    assert (
        await offline.official.provision_bundled_channels(offline.loader) == {}
    )
    assert marker.read_text() == "preserve user source"
    assert loaded().channel_plugin_state.legacy_pending == []


@pytest.mark.asyncio
async def test_c6_uninstall_tombstone_blocks_preset_and_pending_resume(
    offline,
):
    from qwenpaw.plugins.lifecycle import UnloadMode

    bundle(offline)
    save_raw(
        offline,
        {"channel_plugin_state": {"version": 1, "preset": "channels-full"}},
    )
    assert (
        await offline.official.provision_bundled_channels(offline.loader) == {}
    )
    report = await offline.loader.lifecycle.unload(
        "feishu",
        UnloadMode.UNINSTALL,
    )
    assert report.clean
    assert "feishu" in loaded().channel_plugin_state.uninstalled
    assert offline.loader.find_installed_plugin_dir("feishu") is None
    assert (
        await offline.official.provision_bundled_channels(offline.loader) == {}
    )
    assert offline.loader.find_installed_plugin_dir("feishu") is None


@pytest.mark.parametrize("corrupt", ["zip", "descriptor", "identity"])
def test_c6_bundled_integrity_rejects_corrupt_bytes_before_source(
    offline,
    corrupt,
):
    bundle(offline)
    index = json.loads((offline.resources / "index.json").read_text())
    row = next(row for row in index["plugins"] if row["plugin_id"] == "feishu")
    if corrupt == "zip":
        (offline.resources / row["filename"]).write_bytes(b"bad zip")
    elif corrupt == "descriptor":
        row["descriptor_sha256"] = "0" * 64
    else:
        index["host_version"] = "wrong-host"
    (offline.resources / "index.json").write_text(json.dumps(index))
    with pytest.raises(ValueError):
        with offline.official.bundled_channel_source("feishu"):
            pytest.fail("Corrupt bundle yielded source")
    assert offline.loader.find_installed_plugin_dir("feishu") is None


def test_c6_scan_failure_does_not_mark_migration_complete(offline):
    workspace = offline.root / "broken-workspace"
    workspace.mkdir()
    (workspace / "agent.json").write_text("{bad-json")
    save_raw(
        offline,
        {
            "agents": {
                "profiles": {
                    "broken": {
                        "name": "broken",
                        "workspace_dir": str(workspace),
                    },
                },
            },
        },
    )
    with pytest.raises(ValueError):
        offline.official.initialize_channel_policy()
    assert loaded().channel_plugin_state.version == 0


def test_c6_fresh_runtime_provisions_audit_visible_site_under_lock(offline):
    runtime = offline.runtime
    assert runtime.dependency_install_target.is_dir()
    assert runtime.dependency_install_target in runtime.dependency_paths
    assert runtime.selected_channels is None
    assert runtime.allows("sample_chat")
    assert not list(runtime.dependency_install_target.iterdir())
