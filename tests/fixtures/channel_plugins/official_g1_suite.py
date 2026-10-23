"""G1 behavior contracts with real static sources and isolated saved state."""

# Pytest fixtures and static checks intentionally inspect host internals.
# pylint: disable=protected-access,redefined-outer-name,import-outside-toplevel
# pylint: disable=missing-function-docstring,missing-class-docstring
# pylint: disable=unused-argument,too-many-lines,too-many-locals
# pylint: disable=use-implicit-booleaness-not-comparison

import json
import importlib.util
import importlib.abc
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from types import SimpleNamespace
import zipfile

import pytest

from qwenpaw.plugins.architecture import PluginManifest
from qwenpaw.plugins.channel_adapter import describe_channel
from qwenpaw.plugins.registry import PluginRegistry

ROOT = Path(__file__).resolve().parents[3]


def packager():
    spec = importlib.util.spec_from_file_location(
        "g1_independent_packager",
        ROOT / "scripts/pack/generate_plugin_metadata.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_inventory():
    """Independently derive delivered artifacts from real source manifests."""
    delivered = {}
    for manifest_path in (ROOT / "plugins/channel").glob("*/plugin.json"):
        manifest = json.loads(manifest_path.read_text())
        descriptor_path = manifest.get("entry", {}).get("descriptor")
        if descriptor_path is None:
            continue
        source = manifest_path.parent
        descriptor = json.loads((source / descriptor_path).read_text())
        key = descriptor["channel_key"]
        assert key not in delivered, "two official sources claim the same key"
        delivered[key] = (manifest["id"], source.name)
    return delivered


@pytest.fixture
def registry():
    previous = PluginRegistry._instance
    PluginRegistry._instance = None
    try:
        yield PluginRegistry()
    finally:
        PluginRegistry._instance = previous


def channel_source(
    parent,
    *,
    plugin_id="new-delivery",
    key="new_delivery",
    source_dir="delivery_layout",
    publish=True,
):
    """Identity and source names are deliberately independent."""
    root = parent / source_dir
    root.mkdir(parents=True)
    manifest = {
        "id": plugin_id,
        "version": "1.0.0",
        "name": "Offline channel",
        "description": "Static configuration remains editable",
        "type": "channel",
        "entry": {"descriptor": "channel.json"},
        "publish": publish,
        "qwenpaw_version": {"min": "2.2.0"},
    }
    descriptor = {
        "schema_version": 2,
        "channel_key": key,
        "label": {"en": "Offline channel", "zh": "离线渠道"},
        "process_mode": "runner_process",
        "dependency_mode": "shared",
        "entrypoint": {
            "scope": "runner",
            "module": "qwenpaw_channel_" + key + ".driver",
            "qualname": "Driver",
        },
        "requirements_file": "requirements.txt",
        "config_schema": {
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean", "default": False},
                "api_token": {"type": "string", "default": ""},
            },
            "additionalProperties": False,
        },
        "config_fields": ["enabled", "api_token"],
        "capabilities": ["channel.generic.v1"],
    }
    (root / "plugin.json").write_text(json.dumps(manifest))
    (root / "channel.json").write_text(json.dumps(descriptor))
    (root / "requirements.txt").write_text("")
    (root / "README.md").write_text("Offline test channel\n")
    package = root / ("qwenpaw_channel_" + key)
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "driver.py").write_text(
        "raise AssertionError('passive path imported channel driver')\n",
    )
    return root, PluginManifest.from_dict(manifest)


def test_descriptor_registers_distinct_owner_key_and_source_without_import(
    tmp_path,
    registry,
):
    source, manifest = channel_source(tmp_path)
    description = describe_channel(source, manifest)
    row = registry.register_channel_descriptor("new-delivery", description)
    assert description.plugin_id == "new-delivery"
    assert description.descriptor.channel_key == "new_delivery"
    assert description.code_root.name == "delivery_layout"
    assert (
        row.plugin_id == "new-delivery" and row.channel_key == "new_delivery"
    )
    assert registry.get_channel_catalog_entry("new_delivery") is row
    assert registry.get_registered_channels() == {}
    with pytest.raises(ValueError, match="(?i)owner"):
        registry.register_channel_descriptor("impostor", description)


@pytest.mark.parametrize(
    "key,owner",
    [
        ("console", "builtin"),
        ("feishu", "feishu"),
        ("dingtalk", "dingtalk"),
        ("slack", "builtin"),
    ],
)
def test_reserved_channel_cannot_be_claimed_by_third_party(
    tmp_path,
    registry,
    key,
    owner,
):
    source, manifest = channel_source(
        tmp_path,
        plugin_id="impostor",
        key=key,
    )
    with pytest.raises(ValueError) as error:
        registry.register_channel_descriptor(
            "impostor",
            describe_channel(source, manifest),
        )
    occupying = source_inventory().get(key, (owner, ""))[0]
    assert occupying in str(
        error.value
    ), "refusal must identify occupying owner"
    assert registry.get_channel_catalog_entry(key) is None


def test_existing_third_party_owner_is_reported_on_collision(
    tmp_path, registry
):
    first, first_manifest = channel_source(
        tmp_path / "first",
        plugin_id="first-owner",
        key="unique_chat",
    )
    row = registry.register_channel_descriptor(
        "first-owner",
        describe_channel(first, first_manifest),
    )
    second, second_manifest = channel_source(
        tmp_path / "second",
        plugin_id="second-owner",
        key="unique_chat",
    )
    with pytest.raises(ValueError, match="first-owner"):
        registry.register_channel_descriptor(
            "second-owner",
            describe_channel(second, second_manifest),
        )
    assert registry.get_channel_catalog_entry("unique_chat") is row


@pytest.mark.parametrize(
    "plugin_id,key,source_dir",
    [
        ("new-delivery", "new_delivery", "delivery_layout"),
        ("independent-owner", "custom_chat", "source-layout"),
    ],
)
def test_public_packaging_resolves_namespaced_entry_and_uses_owner_zip_root(
    tmp_path,
    plugin_id,
    key,
    source_dir,
):
    source, _ = channel_source(
        tmp_path / "plugins/channel",
        plugin_id=plugin_id,
        key=key,
        source_dir=source_dir,
    )
    index, failed = packager().discover_and_pack(
        tmp_path / "plugins",
        tmp_path / "dist",
        "/offline/plugins",
    )
    assert failed == []
    row = index["files"][plugin_id + "-1.0.0"]
    assert row["plugin_id"] == plugin_id
    assert row["url"] == (
        "/offline/plugins/channel/"
        + plugin_id
        + "/"
        + plugin_id
        + "-1.0.0.zip"
    )
    archive = tmp_path / "dist/channel" / plugin_id / row["filename"]
    with zipfile.ZipFile(archive) as packed:
        names = set(packed.namelist())
        assert names and all(
            name.startswith(plugin_id + "/") for name in names
        )
        assert plugin_id + "/qwenpaw_channel_" + key + "/driver.py" in names
        assert plugin_id + "/channel.json" in names
    assert source.exists()


@pytest.mark.parametrize(
    "change", ["missing", "excluded", "symlink", "traversal"]
)
def test_namespaced_packaging_refuses_invalid_runtime_source(tmp_path, change):
    source, manifest = channel_source(
        tmp_path,
        plugin_id="custom-chat",
        key="custom_chat",
    )
    driver = source / "qwenpaw_channel_custom_chat/driver.py"
    data = json.loads((source / "plugin.json").read_text())
    if change == "missing":
        driver.unlink()
    elif change == "excluded":
        data["pack_exclude"] = ["qwenpaw_channel_custom_chat"]
    elif change == "symlink":
        outside = tmp_path / "outside.py"
        driver.rename(outside)
        driver.symlink_to(outside)
    else:
        descriptor = json.loads((source / "channel.json").read_text())
        descriptor["entrypoint"]["module"] = "../outside"
        (source / "channel.json").write_text(json.dumps(descriptor))
    with pytest.raises((ValueError, FileNotFoundError)):
        packager()._zip_plugin(source, tmp_path / "out.zip", data)
    assert manifest.id == "custom-chat"


DELIVERY = {
    "channel_key": "new_delivery",
    "plugin_id": "new-delivery",
    "source_dir": "delivery_layout",
    "icon": "azure.svg",
    "doc_url": "https://example.invalid/azure-channel",
}


def delivered_fixture(monkeypatch):
    """Inject one delivered inventory record, never fake a tested function."""
    from qwenpaw.plugins import official_channel_catalog as inventory
    from qwenpaw.app.channels import catalog
    from qwenpaw.plugins import official_channels

    assert DELIVERY["channel_key"] not in inventory.official_channel_owners()
    assert inventory.official_channel_for_plugin(DELIVERY["plugin_id"]) is None
    monkeypatch.setattr(
        inventory,
        "OFFICIAL_CHANNELS",
        (*inventory.OFFICIAL_CHANNELS, DELIVERY),
    )
    owners = inventory.official_channel_owners()
    monkeypatch.setattr(catalog, "OFFICIAL_CHANNEL_OWNERS", owners)
    if hasattr(official_channels, "OFFICIAL_CHANNEL_OWNERS"):
        monkeypatch.setattr(
            official_channels, "OFFICIAL_CHANNEL_OWNERS", owners
        )
    return inventory


@pytest.fixture
def saved_host(tmp_path, monkeypatch, registry):
    from qwenpaw.config import utils

    host = tmp_path / "host"
    host.mkdir()
    monkeypatch.setattr(utils, "WORKING_DIR", host)
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", host)
    monkeypatch.setattr("qwenpaw.constant.PLUGINS_DIR", host / "plugins")
    monkeypatch.setattr(utils, "_config_cache", None)
    monkeypatch.setattr(utils, "_config_mtime", None)
    monkeypatch.delenv("QWENPAW_CHANNEL_PRESET", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    (host / "config.json").write_text("{}")
    return host / "config.json"


def test_delivered_inventory_matches_owners_builtin_reservations_and_sources():
    from qwenpaw.plugins import official_channel_catalog as inventory
    from qwenpaw.app.channels.catalog import OFFICIAL_CHANNEL_OWNERS
    from qwenpaw.app.channels.registry import BUILTIN_CHANNEL_KEYS

    rows = inventory.OFFICIAL_CHANNELS
    expected = source_inventory()
    assert set(expected) == {
        "azure_bot",
        "dingtalk",
        "discord",
        "feishu",
        "imessage",
        "matrix",
        "mattermost",
        "mqtt",
        "onebot",
        "qq",
        "sip",
        "slack",
        "telegram",
        "voice",
        "wechat",
        "wecom",
        "xiaoyi",
        "yuanbao",
    }
    assert {
        row["channel_key"]: (row["plugin_id"], row["source_dir"])
        for row in rows
    } == expected
    assert inventory.official_channel_owners() == OFFICIAL_CHANNEL_OWNERS
    assert len({row["plugin_id"] for row in rows}) == len(rows)
    for row in rows:
        assert set(row) == {
            "channel_key",
            "plugin_id",
            "source_dir",
            "icon",
            "doc_url",
        }
        assert row["channel_key"] not in BUILTIN_CHANNEL_KEYS
        source = ROOT / "plugins/channel" / row["source_dir"]
        manifest = PluginManifest.from_dict(
            json.loads((source / "plugin.json").read_text())
        )
        description = describe_channel(source, manifest)
        assert description.plugin_id == row["plugin_id"]
        assert description.descriptor.channel_key == row["channel_key"]
        assert inventory.official_channel_for_plugin(row["plugin_id"]) == row
    assert BUILTIN_CHANNEL_KEYS == frozenset({"console"})
    assert expected["azure_bot"] == ("azure-bot", "azure_bot")
    for source in (ROOT / "plugins/channel").glob("*/plugin.json"):
        data = json.loads(source.read_text())
        if "descriptor" not in data.get("entry", {}):
            assert inventory.official_channel_for_plugin(data["id"]) is None


@pytest.mark.parametrize(
    "selection,admitted",
    [
        (frozenset({"new_delivery"}), True),
        (frozenset({"new-delivery"}), False),
        (frozenset(), False),
        (None, True),
    ],
)
def test_runtime_selection_uses_trusted_channel_key_not_owner(
    tmp_path,
    selection,
    admitted,
):
    from qwenpaw.plugins.channel_adapter import (
        ChannelBackend,
        ChannelRuntimeSettings,
    )

    source, manifest = channel_source(tmp_path)
    description = describe_channel(source, manifest)
    runtime = ChannelRuntimeSettings(
        python_executable=sys.executable,
        support_root=ROOT / "src",
        qwenpaw_version="2.2.2b4",
        selected_channels=selection,
    )
    backend = ChannelBackend(SimpleNamespace(runtime_settings=lambda: runtime))
    assert (backend.runtime_for(description) is runtime) is admitted


@pytest.mark.parametrize("where", ["global", "agent"])
def test_version_one_upgrade_captures_new_channel_once_and_preserves_disables(
    saved_host,
    tmp_path,
    monkeypatch,
    where,
):
    from qwenpaw.plugins.official_channels import initialize_channel_policy
    from qwenpaw.config.utils import load_config, mutate_config

    inventory = delivered_fixture(monkeypatch)
    delivered_keys = {
        row["channel_key"] for row in inventory.OFFICIAL_CHANNELS
    }
    values = {
        "channel_plugin_state": {"version": 1, "preset": "light"},
        "channels": {"feishu": {"enabled": True}},
        "plugins": {"new-delivery": {"enabled": False}},
    }
    active = {
        "channels": {
            "new_delivery": {"enabled": True, "api_token": "offline-only"}
        }
    }
    agent_path, before = None, None
    if where == "global":
        values["channels"].update(active["channels"])
    else:
        workspace = tmp_path / "legacy-workspace"
        workspace.mkdir()
        agent_path = workspace / "agent.json"
        agent_path.write_text(json.dumps(active))
        before = agent_path.read_bytes()
        values["agents"] = {
            "profiles": {
                "old": {"name": "old", "workspace_dir": str(workspace)},
            }
        }
    saved_host.write_text(json.dumps(values))
    initialize_channel_policy()
    first = load_config()
    assert first.channel_plugin_state.legacy_pending == ["new-delivery"]
    assert set(first.channel_plugin_state.legacy_captured) == delivered_keys
    assert first.plugins["new-delivery"]["enabled"] is False
    assert first.channel_plugin_state.preset == "light"
    if where == "agent":
        assert agent_path.read_bytes() == before

    def consumed(config):
        config.channel_plugin_state.legacy_pending = []

    mutate_config(consumed)
    initialize_channel_policy()
    assert load_config().channel_plugin_state.legacy_pending == []


@pytest.mark.parametrize("tombstone", ["new-delivery"])
def test_new_owner_migration_respects_plugin_id_tombstone(
    saved_host, monkeypatch, tombstone
):
    from qwenpaw.plugins.official_channels import initialize_channel_policy
    from qwenpaw.config.utils import load_config

    delivered_fixture(monkeypatch)
    saved_host.write_text(
        json.dumps(
            {
                "channel_plugin_state": {
                    "version": 1,
                    "uninstalled": [tombstone],
                },
                "channels": {"new_delivery": {"enabled": True}},
            }
        )
    )
    initialize_channel_policy()
    state = load_config().channel_plugin_state
    assert state.legacy_pending == []
    assert "new_delivery" in state.legacy_captured
    assert state.uninstalled == ["new-delivery"]


def test_new_inventory_scan_failure_does_not_capture_and_can_retry(
    saved_host,
    tmp_path,
    monkeypatch,
):
    from qwenpaw.plugins.official_channels import initialize_channel_policy
    from qwenpaw.config.utils import load_config

    delivered_fixture(monkeypatch)
    workspace = tmp_path / "broken-agent"
    workspace.mkdir()
    agent_path = workspace / "agent.json"
    agent_path.write_text("{broken-json")
    saved_host.write_text(
        json.dumps(
            {
                "channel_plugin_state": {"version": 1},
                "agents": {
                    "profiles": {
                        "old": {"name": "old", "workspace_dir": str(workspace)}
                    }
                },
            }
        )
    )
    before = saved_host.read_bytes()
    with pytest.raises(ValueError):
        initialize_channel_policy()
    assert saved_host.read_bytes() == before
    agent_path.write_text(
        json.dumps({"channels": {"new_delivery": {"enabled": True}}})
    )
    initialize_channel_policy()
    assert load_config().channel_plugin_state.legacy_pending == [
        "new-delivery"
    ]


def resource_bundle(tmp_path, monkeypatch):
    """Write authenticated fixture resources independently of the packager."""
    from qwenpaw.__version__ import __version__
    from qwenpaw.plugins import official_channels

    inventory = delivered_fixture(monkeypatch)
    resources = tmp_path / "resources"
    resources.mkdir()
    azure_source, _ = channel_source(tmp_path / "source", publish=True)
    rows = []
    for official in sorted(
        inventory.OFFICIAL_CHANNELS, key=lambda row: row["plugin_id"]
    ):
        source = (
            azure_source
            if official["plugin_id"] == "new-delivery"
            else ROOT / "plugins/channel" / official["source_dir"]
        )
        data = json.loads((source / "plugin.json").read_text())
        plugin_id = data["id"]
        filename = plugin_id + "-" + data["version"] + ".zip"
        archive = resources / filename
        with zipfile.ZipFile(archive, "w") as packed:
            for path in sorted(source.rglob("*")):
                if path.is_file() and "__pycache__" not in path.parts:
                    packed.write(
                        path,
                        plugin_id + "/" + path.relative_to(source).as_posix(),
                    )

        def digest(path):
            return hashlib.sha256(path.read_bytes()).hexdigest()

        rows.append(
            {
                "plugin_id": plugin_id,
                "version": data["version"],
                "filename": filename,
                "sha256": digest(archive),
                "descriptor_sha256": digest(source / "channel.json"),
                "requirements_sha256": digest(source / "requirements.txt"),
                "qwenpaw_version": data["qwenpaw_version"],
            }
        )
    (resources / "index.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "host_version": __version__,
                "plugins": rows,
            }
        )
    )
    monkeypatch.setattr(official_channels, "_resource_root", lambda: resources)
    return resources


def test_uninstalled_owner_reads_trusted_schema_labels_icon_and_repair(
    saved_host,
    tmp_path,
    monkeypatch,
    registry,
):
    from qwenpaw.app.channels.catalog import get_configurable_channel_catalog

    resource_bundle(tmp_path, monkeypatch)
    saved_host.write_text(
        json.dumps({"plugins": {"new-delivery": {"enabled": False}}})
    )
    row = get_configurable_channel_catalog()["new_delivery"]
    assert row["plugin_id"] == row["owner"] == "new-delivery"
    assert row["availability"] == "missing_code"
    assert row["global_enabled"] is False
    assert row["label"] == "Offline channel"
    assert row["defaults"]["api_token"] == ""
    assert {field["name"] for field in row["config_fields"]} == {
        "enabled",
        "api_token",
    }
    assert (
        row["icon"] == DELIVERY["icon"]
        and row["doc_url"] == DELIVERY["doc_url"]
    )
    assert row["repair"] == {
        "action": "install",
        "plugin_id": "new-delivery",
        "source": "bundled:new-delivery",
    }
    assert registry.get_registered_channels() == {}
    assert not (saved_host.parent / "plugins").exists()


def test_official_public_source_is_trusted_without_publish_false(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.plugins import official_channels

    resource_bundle(tmp_path, monkeypatch)
    with official_channels.bundled_channel_source("new-delivery") as source:
        assert source.name == "new-delivery"
        assert (
            json.loads((source / "plugin.json").read_text())["publish"] is True
        )
        description = describe_channel(
            source,
            PluginManifest.from_dict(
                json.loads((source / "plugin.json").read_text())
            ),
        )
        assert description.descriptor.channel_key == "new_delivery"
    assert not source.exists()
    static = official_channels.bundled_channel_description("new-delivery")
    assert static.plugin_id == "new-delivery"
    assert (
        static.descriptor.config_schema["properties"]["api_token"]["default"]
        == ""
    )


@pytest.mark.parametrize(
    "corrupt",
    ["archive", "descriptor", "requirements", "version", "host", "owner"],
)
def test_public_official_trust_still_rejects_changed_identity_and_hashes(
    tmp_path,
    monkeypatch,
    corrupt,
):
    from qwenpaw.plugins import official_channels

    resources = resource_bundle(tmp_path, monkeypatch)
    index_path = resources / "index.json"
    index = json.loads(index_path.read_text())
    row = next(
        item
        for item in index["plugins"]
        if item["plugin_id"] == "new-delivery"
    )
    if corrupt == "archive":
        (resources / row["filename"]).write_bytes(b"corrupt archive")
    elif corrupt in {"descriptor", "requirements"}:
        row[corrupt + "_sha256"] = "0" * 64
    elif corrupt == "version":
        row["version"] = "999.0.0"
    elif corrupt == "host":
        index["host_version"] = "wrong-host"
    else:
        row["plugin_id"] = "impostor"
    index_path.write_text(json.dumps(index))
    with pytest.raises(ValueError):
        with official_channels.bundled_channel_source("new-delivery"):
            pytest.fail("corrupt official source was yielded")


@pytest.mark.asyncio
async def test_loader_catalogues_owner_and_runtime_by_channel_key(
    saved_host,
    tmp_path,
    registry,
):
    from qwenpaw.plugins.loader import PluginLoader
    from qwenpaw.plugins.channel_adapter import ChannelRuntimeSettings

    source, manifest = channel_source(tmp_path)
    runtime = ChannelRuntimeSettings(
        python_executable=sys.executable,
        support_root=ROOT / "src",
        qwenpaw_version="2.2.2b4",
        selected_channels=frozenset({"new_delivery"}),
    )
    loader = PluginLoader(
        [saved_host.parent / "plugins"], channel_runtime=runtime
    )
    record = await loader.load_plugin(manifest, source, activate=False)
    row = registry.get_channel_catalog_entry("new_delivery")
    assert row is not None and row.plugin_id == "new-delivery"
    assert row.runtime_settings is runtime
    assert record.enabled is True and record.status == "registered"
    assert (
        loader._channel_backend.runtime_for(record.backend_binding.description)
        is runtime
    )
    assert registry.get_registered_channels() == {}


@pytest.mark.asyncio
async def test_distinct_owner_activation_checks_workspace_channel_binding(
    saved_host,
    tmp_path,
    registry,
):
    from qwenpaw.app.channels.manager import ChannelManager
    from qwenpaw.config.config import Config
    from qwenpaw.plugins.loader import PluginLoader
    from qwenpaw.plugins.channel_adapter import ChannelRuntimeSettings
    from qwenpaw.plugins.workspace_projector import WorkspaceProjector

    source, manifest = channel_source(tmp_path)
    runtime = ChannelRuntimeSettings(
        python_executable=sys.executable,
        support_root=ROOT / "src",
        qwenpaw_version="2.2.2b4",
        selected_channels=frozenset({"new_delivery"}),
    )
    loader = PluginLoader(
        [saved_host.parent / "plugins"], channel_runtime=runtime
    )
    record = await loader.load_plugin(manifest, source, activate=False)

    async def unused_agent(_request):
        raise AssertionError("activation executed Agent")

    existing = record.backend_binding.description.payload.create_proxy(
        unused_agent,
        {"enabled": True},
        python_executable=sys.executable,
        support_root=ROOT / "src",
        instance_id="workspace",
        generation=1,
        qwenpaw_version="2.2.2b4",
    )
    manager = ChannelManager([existing])
    workspace = SimpleNamespace(
        agent_id="workspace",
        channel_manager=manager,
        _config=Config.model_validate(
            {"channels": {"new_delivery": {"enabled": True}}}
        ),
    )
    registry.projector = WorkspaceProjector(
        live_workspaces=lambda: [workspace]
    )
    with pytest.raises(RuntimeError, match="CHANNEL_ALREADY_OWNED"):
        await loader._channel_backend.before_activate(
            record.backend_binding.description
        )
    assert existing.channel_process.health_snapshot()["pid"] is None


@pytest.mark.asyncio
async def test_new_owner_seed_uninstall_preserves_data_and_never_recaptures(
    saved_host,
    tmp_path,
    monkeypatch,
    registry,
):
    from qwenpaw.plugins.loader import PluginLoader
    from qwenpaw.plugins import official_channels
    from qwenpaw.plugins.lifecycle import UnloadMode
    from qwenpaw.plugins.channel_adapter import ChannelRuntimeSettings
    from qwenpaw.plugins.workspace_projector import WorkspaceProjector
    from qwenpaw.config.utils import load_config

    resource_bundle(tmp_path, monkeypatch)
    saved_host.write_text(
        json.dumps(
            {
                "channel_plugin_state": {"version": 1},
                "channels": {
                    "new_delivery": {
                        "enabled": True,
                        "api_token": "offline-only",
                    }
                },
                "plugins": {
                    "new-delivery": {
                        "enabled": False,
                        "owner_setting": "preserve-until-uninstall",
                    }
                },
            }
        )
    )
    business_data = saved_host.parent / "new_delivery-auth.json"
    business_data.write_text('{"offline_fixture": true}')
    runtime = ChannelRuntimeSettings(
        python_executable=sys.executable,
        support_root=ROOT / "src",
        qwenpaw_version="2.2.2b4",
        selected_channels=frozenset({"new_delivery"}),
    )
    loader = PluginLoader(
        [saved_host.parent / "plugins"], channel_runtime=runtime
    )
    registry.projector = WorkspaceProjector(live_workspaces=lambda: [])
    assert await official_channels.provision_bundled_channels(loader) == {}
    installed = loader.find_installed_plugin_dir("new-delivery")
    assert installed == saved_host.parent / "plugins/new-delivery"
    assert (installed / "qwenpaw_channel_new_delivery/driver.py").is_file()
    assert (
        registry.get_channel_catalog_entry("new_delivery").global_enabled
        is False
    )
    first = load_config()
    assert first.channel_plugin_state.legacy_pending == []
    assert first.plugins["new-delivery"]["enabled"] is False
    assert loader.find_installed_plugin_dir("feishu") is None
    report = await loader.lifecycle.unload(
        "new-delivery", UnloadMode.UNINSTALL
    )
    assert report.clean
    after = load_config()
    assert "new-delivery" not in after.plugins
    assert "new-delivery" in after.channel_plugin_state.uninstalled
    assert (
        after.channels.model_dump()["new_delivery"]["api_token"]
        == "offline-only"
    )
    assert business_data.read_text() == '{"offline_fixture": true}'
    assert loader.find_installed_plugin_dir("new-delivery") is None
    assert await official_channels.provision_bundled_channels(loader) == {}
    assert loader.find_installed_plugin_dir("new-delivery") is None


def bundle_project(tmp_path):
    """Real release tree plus one controlled, not-yet-delivered owner."""
    from qwenpaw.plugins.official_channel_catalog import OFFICIAL_CHANNELS

    project = tmp_path / "project"
    sources = project / "plugins/channel"
    records = (*OFFICIAL_CHANNELS, DELIVERY)
    requirements = set()
    for row in OFFICIAL_CHANNELS:
        source = ROOT / "plugins/channel" / row["source_dir"]
        shutil.copytree(source, sources / row["source_dir"])
        requirements.update(
            line.strip()
            for line in (source / "requirements.txt").read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    channel_source(sources, publish=True)
    static_file = project / "src/qwenpaw/plugins/official_channel_catalog.py"
    static_file.parent.mkdir(parents=True)
    static_file.write_text("OFFICIAL_CHANNELS = " + repr(records) + "\n")
    (project / "pyproject.toml").write_text(
        "[project.optional-dependencies]\nchannels = "
        + json.dumps(sorted(requirements))
        + "\n",
    )
    return project, records


def test_bundle_uses_inventory_sources_owner_roots_and_public_policy(
    tmp_path,
):
    project, records = bundle_project(tmp_path)
    destination = tmp_path / "bundled"
    destination.mkdir()
    stale = destination / "new-delivery-obsolete.zip"
    stale.write_bytes(b"obsolete")
    index_path = packager().build_official_channel_bundle(
        project,
        destination,
        host_version="2.2.2b4",
    )
    index = json.loads(index_path.read_text())
    assert [row["plugin_id"] for row in index["plugins"]] == sorted(
        row["plugin_id"] for row in records
    )
    assert not stale.exists()
    for row in index["plugins"]:
        archive = destination / row["filename"]
        assert (
            hashlib.sha256(archive.read_bytes()).hexdigest() == row["sha256"]
        )
        with zipfile.ZipFile(archive) as packed:
            names = set(packed.namelist())
            assert all(
                name.startswith(row["plugin_id"] + "/") for name in names
            )
            manifest = json.loads(
                packed.read(row["plugin_id"] + "/plugin.json")
            )
            descriptor = packed.read(row["plugin_id"] + "/channel.json")
            assert manifest["id"] == row["plugin_id"]
            assert (
                hashlib.sha256(descriptor).hexdigest()
                == row["descriptor_sha256"]
            )
    public, failed = packager().discover_and_pack(
        project / "plugins", tmp_path / "public", "/offline"
    )
    assert failed == []
    assert set(public["files"]) == {"azure-bot-2.0.0", "new-delivery-1.0.0"}


@pytest.mark.parametrize(
    "change", ["owner", "excluded_auxiliary", "extra_requirements"]
)
def test_bundle_refuses_inventory_owner_mismatch_or_incomplete_runtime(
    tmp_path, change
):
    project, _ = bundle_project(tmp_path)
    azure = project / "plugins/channel/delivery_layout"
    data = json.loads((azure / "plugin.json").read_text())
    if change == "owner":
        data["id"] = "impostor"
        (azure / "plugin.json").write_text(json.dumps(data))
    elif change == "excluded_auxiliary":
        (azure / "qwenpaw_channel_new_delivery/protocol.json").write_text("{}")
        data["pack_exclude"] = ["qwenpaw_channel_new_delivery/protocol.json"]
        (azure / "plugin.json").write_text(json.dumps(data))
    else:
        (azure / "requirements.txt").write_text(
            "example-offline-sdk>=1; sys_platform == 'darwin'\n"
        )
    with pytest.raises(ValueError):
        packager().build_official_channel_bundle(
            project, tmp_path / "dist", host_version="2.2.2b4"
        )


@pytest.mark.parametrize("key", sorted(source_inventory()))
def test_delivered_schema_properties_defaults_and_fields_match_host_model(key):
    from qwenpaw.config.config import ChannelConfig

    plugin_id, source_dir = source_inventory()[key]
    source = ROOT / "plugins/channel" / source_dir
    descriptor = json.loads((source / "channel.json").read_text())
    properties = descriptor["config_schema"]["properties"]
    assert set(descriptor["config_fields"]) == set(properties)
    # Pydantic exposes this metaclass mapping dynamically.
    fields = dict(ChannelConfig.model_fields)
    if key in fields:
        model = fields[key].annotation
        host_properties = model.model_json_schema()["properties"]
        assert set(properties) == set(host_properties)
        for name, field in host_properties.items():
            for constraint, value in field.items():
                assert properties[name][constraint] == value
        assert {
            name: field.get("default")
            for name, field in properties.items()
            if "default" in field
        } == model().model_dump(mode="json")
    assert plugin_id == json.loads((source / "plugin.json").read_text())["id"]


@pytest.mark.parametrize(
    "domain,valid",
    [
        ("feishu", True),
        ("lark", True),
        ("https://offline.invalid", True),
        ("arbitrary-domain", False),
    ],
)
def test_feishu_descriptor_domain_validation_matches_existing_host(
    domain, valid
):
    from qwenpaw.config.config import FeishuConfig
    from qwenpaw.plugins.channel_config import validate_channel_config

    schema = json.loads(
        (ROOT / "plugins/channel/feishu/channel.json").read_text()
    )["config_schema"]
    if valid:
        assert FeishuConfig(domain=domain).domain == domain
        assert (
            validate_channel_config(schema, {"domain": domain})["domain"]
            == domain
        )
    else:
        with pytest.raises(ValueError):
            FeishuConfig(domain=domain)
        with pytest.raises(ValueError):
            validate_channel_config(schema, {"domain": domain})


def test_new_disabled_channel_is_captured_once_without_future_revival(
    saved_host,
    monkeypatch,
):
    from qwenpaw.plugins.official_channels import initialize_channel_policy
    from qwenpaw.config.utils import load_config, mutate_config

    delivered_fixture(monkeypatch)
    saved_host.write_text(
        json.dumps(
            {
                "channel_plugin_state": {"version": 1},
                "channels": {"new_delivery": {"enabled": False}},
            }
        )
    )
    initialize_channel_policy()
    assert "new_delivery" in load_config().channel_plugin_state.legacy_captured
    assert load_config().channel_plugin_state.legacy_pending == []

    def enable(config):
        config.channels.new_delivery["enabled"] = True

    mutate_config(enable)
    initialize_channel_policy()
    assert load_config().channel_plugin_state.legacy_pending == []


def test_passive_trusted_catalog_does_not_attempt_driver_sdk_or_spawn(
    saved_host,
    tmp_path,
    monkeypatch,
):
    import asyncio
    from qwenpaw.app.channels.catalog import get_configurable_channel_catalog

    resource_bundle(tmp_path, monkeypatch)
    attempts = []

    class ImportGuard(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if (
                fullname.startswith("qwenpaw_channel_")
                or fullname == "lark_oapi"
            ):
                attempts.append(fullname)
                raise AssertionError(
                    "passive catalog attempted implementation import"
                )

    async def no_spawn(*args, **kwargs):
        attempts.append("subprocess")
        raise AssertionError("passive catalog attempted subprocess")

    monkeypatch.setattr(sys, "meta_path", [ImportGuard(), *sys.meta_path])
    monkeypatch.setattr(asyncio, "create_subprocess_exec", no_spawn)
    row = get_configurable_channel_catalog()["new_delivery"]
    assert row["defaults"]["enabled"] is False
    assert attempts == []


def stage_module():
    spec = importlib.util.spec_from_file_location(
        "g1_independent_stage",
        ROOT / "scripts/pack-tauri/stage_channel_runtime.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def staged_resources(tmp_path):
    project, _ = bundle_project(tmp_path)
    site = tmp_path / "staged/site"
    destination = site / "qwenpaw/official_channels"
    packager().build_official_channel_bundle(
        project,
        destination,
        host_version="2.2.2b4",
    )
    inventory = site / "qwenpaw/plugins/official_channel_catalog.py"
    inventory.parent.mkdir(parents=True)
    shutil.copyfile(
        project / "src/qwenpaw/plugins/official_channel_catalog.py", inventory
    )
    return site


def test_stage_static_resources_validate_public_alias_without_sdk(tmp_path):
    site = staged_resources(tmp_path)
    stage_module()._validate_official_resources(site, "2.2.2b4")
    assert not list(site.rglob("__pycache__"))


@pytest.mark.parametrize(
    "change",
    [
        "missing_owner",
        "unexpected_owner",
        "unsafe_filename",
        "descriptor",
        "requirements",
        "manifest_version",
        "root",
        "host",
    ],
)
def test_stage_refuses_corrupt_identity_before_publishing_runtime(
    tmp_path, change
):
    site = staged_resources(tmp_path)
    resources = site / "qwenpaw/official_channels"
    index_path = resources / "index.json"
    data = json.loads(index_path.read_text())
    row = next(
        item for item in data["plugins"] if item["plugin_id"] == "new-delivery"
    )
    if change == "missing_owner":
        data["plugins"].remove(row)
    elif change == "unexpected_owner":
        row["plugin_id"] = "impostor"
    elif change == "unsafe_filename":
        row["filename"] = "../outside.zip"
    elif change in {"descriptor", "requirements"}:
        row[change + "_sha256"] = "0" * 64
    elif change == "manifest_version":
        row["version"] = "999.0.0"
    elif change == "host":
        data["host_version"] = "wrong-host"
    else:
        archive = resources / row["filename"]
        with zipfile.ZipFile(archive) as zipped:
            entries = {name: zipped.read(name) for name in zipped.namelist()}
        with zipfile.ZipFile(archive, "w") as zipped:
            for name, content in entries.items():
                zipped.writestr(
                    name.replace("new-delivery/", "new_delivery/", 1), content
                )
        row["sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    index_path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        stage_module()._validate_official_resources(site, "2.2.2b4")
    assert not (site.parent / "runtime.json").exists()


def test_real_sdist_contains_inventory_sources_and_rebuildable_public_alias(
    tmp_path,
):
    project, records = bundle_project(tmp_path)
    shutil.copyfile(ROOT / "setup.py", project / "setup.py")
    shutil.copyfile(ROOT / "MANIFEST.in", project / "MANIFEST.in")
    script = project / "scripts/pack/generate_plugin_metadata.py"
    script.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "scripts/pack/generate_plugin_metadata.py", script)
    (project / "src/qwenpaw/__init__.py").write_text(
        "raise AssertionError('sdist imported host package')\n",
    )
    old_project = (project / "pyproject.toml").read_text()
    (project / "pyproject.toml").write_text(
        '[project]\nname = "qwenpaw"\nversion = "2.2.2b4"\n'
        + old_project
        + '\n[tool.setuptools.packages.find]\nwhere = ["src"]\n',
    )
    channel_source(
        project / "plugins/channel",
        plugin_id="not-delivered",
        key="not_delivered",
        source_dir="not_delivered",
    )
    destination = tmp_path / "sdist"
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "setup.py",
            "sdist",
            "--dist-dir",
            str(destination),
        ],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    archives = list(destination.glob("*.tar.gz"))
    assert len(archives) == 1
    extracted = tmp_path / "extracted"
    with tarfile.open(archives[0]) as archive:
        names = archive.getnames()
        root = names[0].split("/")[0]
        for record in records:
            source = root + "/plugins/channel/" + record["source_dir"]
            assert source + "/plugin.json" in names
            assert source + "/channel.json" in names
            assert source + "/requirements.txt" in names
            assert source + "/README.md" in names
        assert not any(
            "/plugins/channel/not_delivered/" in name for name in names
        )
        archive.extractall(extracted, filter="data")
    rebuilt = packager().build_official_channel_bundle(
        extracted / root,
        tmp_path / "rebuilt",
        host_version="2.2.2b4",
    )
    assert [
        row["plugin_id"] for row in json.loads(rebuilt.read_text())["plugins"]
    ] == sorted(record["plugin_id"] for record in records)
