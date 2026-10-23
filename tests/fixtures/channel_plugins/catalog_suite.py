# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,import-outside-toplevel
# pylint: disable=missing-function-docstring,missing-class-docstring
# pylint: disable=unused-argument
"""C1 metadata contracts, independent of vendor SDK and executable plugins."""

import asyncio
from dataclasses import FrozenInstanceError, replace
import importlib
import importlib.abc
import importlib.util
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace as NS

import pytest

from qwenpaw.plugins.architecture import PluginManifest, PluginRecord
from qwenpaw.plugins.registry import PluginRegistry, ChannelRegistration

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def registry():
    old = PluginRegistry._instance
    PluginRegistry._instance = None
    try:
        yield PluginRegistry()
    finally:
        PluginRegistry._instance = old


def manifest_data(key="feishu"):
    return {
        "id": key,
        "version": "1.0.0",
        "name": "Candidate name",
        "description": "Candidate description",
        "type": "channel",
        "entry": {"descriptor": "channel.json"},
        "publish": False,
    }


def candidate(tmp_path, key="feishu"):
    """Build declared installed layout without importing candidate code."""
    source = tmp_path / key
    source.mkdir(parents=True)
    original = (
        ROOT
        / "plugins/channel"
        / (key if key in {"feishu", "dingtalk"} else "feishu")
    )
    descriptor = json.loads((original / "channel.json").read_text())
    descriptor["channel_key"] = key
    descriptor["entrypoint"]["module"] = key + ".driver"
    data = manifest_data(key)
    (source / "plugin.json").write_text(json.dumps(data))
    (source / "channel.json").write_text(json.dumps(descriptor))
    shutil.copyfile(original / "requirements.txt", source / "requirements.txt")
    package = source / key
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "driver.py").write_text(
        "raise AssertionError('metadata discovery imported driver')\n",
    )
    return source, PluginManifest.from_dict(data)


def describe(source, manifest):
    from qwenpaw.plugins.channel_adapter import describe_channel

    return describe_channel(source, manifest)


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/channel.json",
        "../channel.json",
        "./channel.json",
        "nested/../channel.json",
        "nested//channel.json",
        "channel\\descriptor.json",
        "C:/channel.json",
        "channel.py",
        " channel.json",
        "channel.json ",
    ],
)
def test_manifest_rejects_noncanonical_descriptor_paths(path):
    data = manifest_data()
    data["entry"]["descriptor"] = path
    with pytest.raises(ValueError):
        PluginManifest.from_dict(data)


@pytest.mark.parametrize(
    "change",
    ["backend", "legacy", "missing_type", "bad_type"],
)
def test_manifest_descriptor_requires_exclusive_backend_and_explicit_type(
    change,
):
    data = manifest_data()
    if change == "backend":
        data["entry"]["backend"] = "plugin.py"
    elif change == "legacy":
        data["entry_point"] = "plugin.py"
    elif change == "missing_type":
        data.pop("type")
        data["meta"] = {"channel": "feishu"}
    else:
        data["type"] = "invalid"
    with pytest.raises(ValueError):
        PluginManifest.from_dict(data)


def test_legacy_python_and_frontend_manifest_remain_compatible():
    old = PluginManifest.from_dict(
        {
            "id": "old",
            "version": "1",
            "entry_point": "plugin.py",
        },
    )
    assert old.entry.backend == "plugin.py"
    new = manifest_data()
    new["entry"]["frontend"] = "index.js"
    assert PluginManifest.from_dict(new).entry.descriptor == "channel.json"


@pytest.mark.parametrize("key", ["feishu", "dingtalk"])
def test_missing_sdk_discovery_is_metadata_only_and_frozen(
    tmp_path,
    monkeypatch,
    key,
):
    source, manifest = candidate(tmp_path, key)
    attempts = []

    class Block(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.split(".")[0] in {
                "lark_oapi",
                "dingtalk_stream",
                "feishu",
                "dingtalk",
            } or fullname.startswith("alibabacloud_"):
                attempts.append(fullname)
                raise AssertionError("metadata import: " + fullname)

    monkeypatch.setattr(sys, "meta_path", [Block(), *sys.meta_path])
    result = describe(source, manifest)
    assert not attempts
    assert result.plugin_id == key and result.version == manifest.version
    assert (
        result.name == manifest.name
        and result.description == manifest.description
    )
    assert result.descriptor.channel_key == key
    assert result.descriptor_path == source / "channel.json"
    assert result.requirements_path == source / "requirements.txt"
    assert result.code_root == source.resolve()
    assert result.requirements and isinstance(result.requirements, tuple)
    with pytest.raises(FrozenInstanceError):
        result.plugin_id = "replacement"


@pytest.mark.parametrize(
    "change",
    [
        "owner",
        "bad_descriptor",
        "descriptor_symlink",
        "requirements_escape",
        "requirements_symlink",
        "requirements_missing",
        "dependencies_diverge",
    ],
)
def test_description_rejects_invalid_owner_files_and_dependency_divergence(
    tmp_path,
    change,
):
    source, manifest = candidate(tmp_path)
    descriptor = source / "channel.json"
    payload = json.loads(descriptor.read_text())
    if change == "owner":
        manifest = manifest.model_copy(update={"id": "other"})
    elif change == "bad_descriptor":
        payload["schema_version"] = 999
        descriptor.write_text(json.dumps(payload))
    elif change == "descriptor_symlink":
        outside = tmp_path / "outside.json"
        descriptor.rename(outside)
        descriptor.symlink_to(outside)
    elif change == "requirements_escape":
        payload["requirements_file"] = "../requirements.txt"
        descriptor.write_text(json.dumps(payload))
    elif change == "requirements_symlink":
        outside = tmp_path / "outside.txt"
        (source / "requirements.txt").rename(outside)
        (source / "requirements.txt").symlink_to(outside)
    elif change == "requirements_missing":
        (source / "requirements.txt").unlink()
    else:
        manifest = manifest.model_copy(
            update={"dependencies": ["invented-sdk==1"]},
        )
    with pytest.raises((ValueError, FileNotFoundError)):
        describe(source, manifest)


def test_requirement_matching_and_sibling_digest_isolation(tmp_path):
    source, manifest = candidate(tmp_path)
    (source / "requirements.txt").write_text("# comment\nlark_oapi >= 1\n")
    manifest = manifest.model_copy(update={"dependencies": ["lark-oapi>=1"]})
    initial = describe(source, manifest)
    sibling = tmp_path / "dingtalk"
    sibling.mkdir()
    (sibling / "driver.py").write_text("unrelated source")
    assert (
        describe(source, manifest).source_revision == initial.source_revision
    )
    copied = tmp_path / "installed" / "feishu"
    shutil.copytree(source, copied)
    assert (
        describe(copied, manifest).source_revision == initial.source_revision
    )
    (source / "feishu" / "driver.py").write_text("changed candidate")
    assert (
        describe(source, manifest).source_revision != initial.source_revision
    )


async def unused_process(_request):
    raise AssertionError("construction called process")


@pytest.mark.parametrize("key", ["feishu", "dingtalk"])
def test_factory_validates_and_snapshots_without_spawn_or_media_writes(
    tmp_path,
    monkeypatch,
    key,
):
    source, manifest = candidate(tmp_path, key)
    description = describe(source, manifest)
    calls = []

    async def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("construction spawned")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    values = {"enabled": True, "allow_from": ["first"]}
    launch = {
        "python_executable": sys.executable,
        "support_root": ROOT / "src",
        "instance_id": "workspace-A",
        "generation": 7,
        "qwenpaw_version": "2.2.2b4",
        "dependency_paths": (),
        "workspace_dir": tmp_path / "workspace",
    }
    proxy = description.create_proxy(unused_process, values, **launch)
    values["allow_from"].append("later")
    spec = proxy._launch_spec
    assert spec.config["allow_from"] == ["first"]
    assert (
        spec.code_root == source
        and spec.descriptor_path == source / "channel.json"
    )
    assert spec.source_revision == description.source_revision
    assert spec.channel_key == key and spec.generation == 7
    assert spec.python_executable == sys.executable
    assert (
        spec.instance_id == "workspace-A" and spec.support_root == ROOT / "src"
    )
    assert not calls and not (tmp_path / "workspace").exists()
    assert proxy.channel_process.health_snapshot()["pid"] is None
    with pytest.raises(ValueError):
        description.create_proxy(unused_process, {"allow_from": 17}, **launch)
    assert not calls


def test_generic_config_factory_succeeds_without_host_model(tmp_path):
    """G1 replaces the old unknown-Config rejection with schema support."""
    from extension_admission_suite import sample_plugin

    source, manifest = sample_plugin(tmp_path, "future")
    description = describe(source, manifest)
    channel = description.create_proxy(
        unused_process,
        {"api_token": "test-token", "options": {"retries": 6}},
        python_executable=sys.executable,
        support_root=ROOT / "src",
        instance_id="w",
        generation=1,
        qwenpaw_version="2.2.2b4",
    )
    assert channel.channel == "future"
    assert channel._launch_spec.config["options"] == {
        "retries": 6,
        "headers": {"X-Test": "yes"},
    }
    assert channel.channel_process.health_snapshot()["pid"] is None


def test_catalog_is_inactive_owner_checked_and_identity_guarded(
    tmp_path,
    registry,
):
    source, manifest = candidate(tmp_path)
    description = describe(source, manifest)
    row = registry.register_channel_descriptor("feishu", description)
    assert row.channel_class is None and row.description_record is description
    assert (
        row.plugin_id == "feishu" and row.description == manifest.description
    )
    assert row.config_fields
    assert registry.get_channel_catalog_entry("feishu") is row
    assert registry.get_channel_catalog()["feishu"] is row
    assert registry.get_channel_registration("feishu") is None
    assert registry.get_registered_channels() == {}
    assert registry.leftover_channel_keys("feishu") == ["feishu"]
    with pytest.raises(ValueError):
        registry.register_channel_descriptor("other-owner", description)
    with pytest.raises(ValueError):
        registry.register_channel_descriptor("feishu", description)
    assert registry.unregister_channel("feishu", expected=row)
    replacement = registry.register_channel_descriptor("feishu", description)
    assert replacement is not row
    assert registry.unregister_channel("feishu", expected=row) is False
    assert registry.get_channel_catalog_entry("feishu") is replacement
    assert registry.unregister_channel("feishu")


def test_other_builtin_static_keys_are_rejected(tmp_path, registry):
    from qwenpaw.app.channels.registry import BUILTIN_CHANNEL_KEYS

    key = "console"
    assert key in BUILTIN_CHANNEL_KEYS
    source, manifest = candidate(tmp_path, key)
    with pytest.raises(ValueError):
        registry.register_channel_descriptor(key, describe(source, manifest))


def test_official_slack_rejects_wrong_owner_and_accepts_rightful_owner(
    tmp_path,
    registry,
):
    source, manifest = candidate(tmp_path, "other")
    descriptor = source / "channel.json"
    payload = json.loads(descriptor.read_text())
    payload["channel_key"] = "slack"
    descriptor.write_text(json.dumps(payload))
    with pytest.raises(
        ValueError,
        match="Channel 'slack' owner 'slack' conflicts with plugin 'other'",
    ):
        describe(source, manifest)
    assert registry.get_channel_catalog_entry("slack") is None

    source, manifest = candidate(tmp_path, "slack")
    description = describe(source, manifest)
    row = registry.register_channel_descriptor("slack", description)
    assert row.plugin_id == "slack" and row.description_record is description
    assert registry.get_channel_catalog_entry("slack") is row


@pytest.mark.asyncio
async def test_static_api_ledger_revoke_cannot_delete_replacement(
    tmp_path,
    registry,
):
    from qwenpaw.plugins.api import PluginApi
    from qwenpaw.plugins.lifecycle import PluginInstance, PluginState
    from qwenpaw.plugins.channel_adapter import StaticChannelDefinition

    source, manifest = candidate(tmp_path)
    description = describe(source, manifest)
    instance = PluginInstance("feishu")
    api = PluginApi("feishu", {})
    api.set_registry(registry)
    api.bind_instance(instance)
    StaticChannelDefinition(description).register(api)
    old = registry.get_channel_catalog_entry("feishu")
    assert old is not None
    assert instance._runtime
    registry.unregister_channel("feishu", expected=old)
    replacement = registry.register_channel_descriptor("feishu", description)
    report = await instance.teardown_runtime()
    assert report.clean
    assert registry.get_channel_catalog_entry("feishu") is replacement
    instance.state = PluginState.DISPOSED
    with pytest.raises(RuntimeError):
        api.register_channel_descriptor(description)


def live_channel(key="custom"):
    class Live:
        channel = key
        uses_manager_queue = False

        def __init__(self):
            self.stops = 0
            self.starts = 0

        async def start(self):
            self.starts += 1

        async def stop(self):
            self.stops += 1

        def set_enqueue(self, _callback):
            pass

    return Live()


@pytest.mark.asyncio
async def test_manager_stale_start_rechecked_inside_actual_lifecycle_lock(
    registry,
):
    from qwenpaw.app.channels.manager import ChannelManager

    current = live_channel()
    manager = ChannelManager([current])
    old = ChannelRegistration("owner", "custom", type(current))
    registry._channels["custom"] = old
    lock = manager._channel_lifecycle_locks.setdefault(
        "custom",
        asyncio.Lock(),
    )
    await lock.acquire()
    task = asyncio.create_task(
        manager.start_one(
            "custom",
            None,
            expected_registration=old,
        ),
    )
    try:
        await asyncio.sleep(0)
        assert (
            not task.done()
        ), "registration must be checked after acquiring lock"
        replacement = replace(old)
        registry._channels["custom"] = replacement
    finally:
        lock.release()
    with pytest.raises(RuntimeError, match="(?i)stale"):
        await task
    assert (
        manager.channels == [current] and current.starts == current.stops == 0
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong_key", [False, True])
async def test_manager_stale_handle_rechecked_inside_actual_lifecycle_lock(
    wrong_key,
):
    from qwenpaw.app.channels.manager import ChannelHandle, ChannelManager

    old = live_channel()
    replacement = live_channel()
    manager = ChannelManager([old])
    lock = manager._channel_lifecycle_locks.setdefault(
        "custom",
        asyncio.Lock(),
    )
    await lock.acquire()
    handle = ChannelHandle("other" if wrong_key else "custom", old)
    task = asyncio.create_task(manager.stop_one("custom", expected=handle))
    try:
        await asyncio.sleep(0)
        assert not task.done(), "handle must be checked after acquiring lock"
        manager.channels = [replacement]
    finally:
        lock.release()
    receipt = await task
    assert receipt.stopped and receipt.detail == "stale binding"
    assert replacement.stops == old.stops == 0
    assert manager.channels == [replacement]
    # Public key-only compatibility still stops the current binding.
    assert (await manager.stop_one("custom")).stopped
    assert replacement.stops == 1 and manager.channels == []


@pytest.mark.asyncio
async def test_old_class_projection_ledger_callback_cannot_revoke_new_intent(
    registry,
    monkeypatch,
):
    from qwenpaw.app.channels.base import BaseChannel
    from qwenpaw.app.channels.manager import ChannelManager
    from qwenpaw.plugins.api import PluginApi
    from qwenpaw.plugins.lifecycle import PluginInstance
    from qwenpaw.plugins.workspace_projector import WorkspaceProjector

    class Legacy(BaseChannel):
        channel = "custom"

    manager = ChannelManager([])
    manager._process = unused_process
    config = NS(channels=NS(custom=NS(enabled=True)))
    workspace = NS(agent_id="w", _config=config, channel_manager=manager)
    registry.projector = WorkspaceProjector(
        live_workspaces=lambda: [workspace],
    )
    monkeypatch.setattr(
        "qwenpaw.plugins.api.get_available_channels",
        lambda: ("custom",),
    )
    created = []

    def instantiate(*args, **kwargs):
        channel = live_channel()
        created.append(channel)
        return channel

    monkeypatch.setattr(
        "qwenpaw.app.channels.manager.instantiate_channel",
        instantiate,
    )
    old_instance = PluginInstance("same-owner", generation=1)
    old_api = PluginApi("same-owner", {})
    old_api.set_registry(registry)
    old_api.bind_instance(old_instance)
    old_api.register_channel(Legacy)
    saved_callbacks = [
        entry.teardown for entry in old_instance._runtime if entry.teardown
    ]
    await registry.projector.project("channel", "custom", "same-owner")
    assert len(created) == 1 and created[0].starts == 1
    # Retain an old callback after the normal first revoke.
    first = await old_instance.teardown_runtime()
    assert first.clean and created[0].stops == 1
    new_instance = PluginInstance("same-owner", generation=2)
    new_api = PluginApi("same-owner", {})
    new_api.set_registry(registry)
    new_api.bind_instance(new_instance)
    new_api.register_channel(Legacy)
    new_row = registry.get_channel_registration("custom")
    await registry.projector.project("channel", "custom", "same-owner")
    new_intent = registry.projector._find("channel", "custom", "same-owner")
    assert len(created) == 2 and created[1].starts == 1
    for callback in saved_callbacks:
        result = callback()
        if hasattr(result, "__await__"):
            await result
    assert registry.get_channel_registration("custom") is new_row
    assert (
        registry.projector._find("channel", "custom", "same-owner")
        is new_intent
    )
    assert manager.channels == [created[1]] and created[1].stops == 0
    assert (await new_instance.teardown_runtime()).clean


def prohibit_loader_side_effects(loader, monkeypatch):
    """A failure below these gates must not silently count as refusal."""

    def forbidden(*args, **kwargs):
        raise AssertionError("descriptor crossed side-effect boundary")

    for name in (
        "_ensure_dependencies_installed",
        "_project_external_runtime",
        "_commit_plugin_transaction",
        "_probe_plugin",
    ):
        if hasattr(loader, name):
            monkeypatch.setattr(loader, name, forbidden)
    monkeypatch.setattr(shutil, "copytree", forbidden)


def file_snapshot(root):
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


@pytest.mark.asyncio
async def test_loader_catalogues_missing_sdk_without_installer_and_unloads(
    tmp_path,
    registry,
    monkeypatch,
):
    from qwenpaw.plugins.loader import PluginLoader
    from qwenpaw.plugins.lifecycle import UnloadMode

    source, manifest = candidate(tmp_path)
    loader = PluginLoader([tmp_path])
    loader.registry = registry
    prohibit_loader_side_effects(loader, monkeypatch)
    record = await loader.load_plugin(manifest, source, activate=False)
    assert record.status == "catalogued" and record.enabled is False
    assert any(
        "channel_runtime_not_integrated" in d for d in record.diagnostics
    )
    assert registry.get_channel_catalog_entry("feishu") is not None
    assert registry.get_registered_channels() == {}
    await loader.activate_all_loaded()
    assert record.status == "catalogued" and record.enabled is False
    assert not loader.lifecycle.get_instance("feishu").activated
    report = await loader.lifecycle.unload("feishu", UnloadMode.UNLOAD)
    assert report.clean
    assert registry.get_channel_catalog_entry("feishu") is None


@pytest.mark.asyncio
async def test_loader_explicit_activate_rejects_before_static_registration(
    tmp_path,
    registry,
    monkeypatch,
):
    from qwenpaw.plugins.loader import PluginLoader

    source, manifest = candidate(tmp_path)
    loader = PluginLoader([tmp_path])
    loader.registry = registry
    prohibit_loader_side_effects(loader, monkeypatch)
    before = file_snapshot(tmp_path)
    with pytest.raises(RuntimeError, match="channel_runtime_not_integrated"):
        await loader._load_plugin_unlocked(manifest, source, activate=True)
    assert registry.get_channel_catalog_entry("feishu") is None
    assert file_snapshot(tmp_path) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation",
    ["activate", "repair", "reload", "install_on", "install_off"],
)
async def test_loader_unsupported_mutations_refuse_before_side_effects(
    tmp_path,
    registry,
    monkeypatch,
    operation,
):
    from qwenpaw.plugins.loader import PluginLoader

    source, manifest = candidate(tmp_path / "incoming")
    install_root = tmp_path / "installed"
    install_root.mkdir()
    loader = PluginLoader([install_root])
    loader.registry = registry
    record = PluginRecord(manifest, source, False, status="catalogued")
    if operation in {"activate", "repair", "reload"}:
        loader._loaded_plugins["feishu"] = record
        loader.lifecycle.ensure_instance("feishu")
    prohibit_loader_side_effects(loader, monkeypatch)
    before = file_snapshot(tmp_path)
    if operation == "reload":
        result = await loader.reload_plugin_unlocked(
            "feishu",
            new_source=source,
        )
        assert not result.ok and result.unchanged
        assert any(
            "channel_runtime_not_integrated" in e for e in result.errors
        )
    else:
        with pytest.raises(
            RuntimeError,
            match="channel_runtime_not_integrated",
        ):
            if operation == "activate":
                await loader.activate_plugin_unlocked("feishu")
            elif operation == "repair":
                await loader.repair_dependencies("feishu")
            else:
                await loader.load_plugin_from_path(
                    source,
                    config={"enabled": operation == "install_on"},
                    install_dir=install_root,
                )
    assert file_snapshot(tmp_path) == before
    assert registry.get_registered_channels() == {}
    if operation in {"activate", "repair", "reload"}:
        assert loader.get_loaded_plugin("feishu") is record


def packer():
    spec = importlib.util.spec_from_file_location(
        "c1_catalog_packer",
        ROOT / "scripts/pack/generate_plugin_metadata.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "change",
    [
        "absolute",
        "traversal",
        "backslash",
        "wrong_type",
        "backend",
        "missing_driver",
        "missing_requirements",
        "bad_descriptor",
    ],
)
def test_pack_rejects_invalid_descriptor_candidate_before_archive(
    tmp_path,
    change,
):
    source, _manifest = candidate(tmp_path)
    data = json.loads((source / "plugin.json").read_text())
    if change in {"absolute", "traversal", "backslash"}:
        data["entry"]["descriptor"] = {
            "absolute": "/channel.json",
            "traversal": "../channel.json",
            "backslash": "nested\\channel.json",
        }[change]
        if change == "traversal":
            shutil.copyfile(source / "channel.json", tmp_path / "channel.json")
        if change == "backslash":
            (source / "nested").mkdir()
            shutil.copyfile(
                source / "channel.json",
                source / "nested/channel.json",
            )
    elif change == "wrong_type":
        data["type"] = "tool"
    elif change == "backend":
        data["entry"]["backend"] = "plugin.py"
        (source / "plugin.py").write_text("raise AssertionError('import')")
    elif change == "missing_driver":
        (source / "feishu/driver.py").unlink()
    elif change == "missing_requirements":
        (source / "requirements.txt").unlink()
    else:
        (source / "channel.json").write_text("{}")
    archive = tmp_path / "candidate.zip"
    with pytest.raises((ValueError, FileNotFoundError)):
        packer()._zip_plugin(source, archive, data)
    assert not archive.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded", [False, True])
async def test_descriptor_enable_refuses_before_persist_for_loaded_or_disk(
    tmp_path,
    registry,
    monkeypatch,
    loaded,
):
    from qwenpaw.plugins.loader import PluginLoader

    source, manifest = candidate(tmp_path / "installed")
    loader = PluginLoader([source.parent])
    loader.registry = registry
    if loaded:
        loader._loaded_plugins["feishu"] = PluginRecord(
            manifest,
            source,
            False,
            status="catalogued",
        )
    before = file_snapshot(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("descriptor enable persisted settings")

    monkeypatch.setattr(
        "qwenpaw.plugins.settings.persist_plugin_settings",
        forbidden,
    )
    with pytest.raises(RuntimeError, match="channel_runtime_not_integrated"):
        await loader.lifecycle.set_enabled("feishu", True)
    assert file_snapshot(tmp_path) == before


@pytest.mark.asyncio
async def test_catalog_config_update_is_unchanged_before_teardown_or_persist(
    tmp_path,
    registry,
    monkeypatch,
):
    from qwenpaw.plugins.loader import PluginLoader

    source, manifest = candidate(tmp_path)
    loader = PluginLoader([tmp_path])
    loader.registry = registry
    instance = loader.lifecycle.ensure_instance("feishu")
    instance.config = {"app_id": "saved"}
    record = PluginRecord(
        manifest,
        source,
        False,
        instance=NS(),
        status="catalogued",
    )
    loader._loaded_plugins["feishu"] = record
    sentinel = ChannelRegistration("feishu", "feishu", None)
    registry._channels["feishu"] = sentinel

    def forbidden(*args, **kwargs):
        raise AssertionError("catalog config crossed mutation boundary")

    monkeypatch.setattr(instance, "teardown_runtime", forbidden)
    monkeypatch.setattr(
        "qwenpaw.plugins.settings.persist_plugin_settings",
        forbidden,
    )
    result = await loader.lifecycle.update_config(
        "feishu",
        {"app_id": "incoming"},
    )
    assert not result.ok and result.unchanged
    assert any(
        "channel_runtime_not_integrated" in error for error in result.errors
    )
    assert instance.config == {"app_id": "saved"}
    assert loader.get_loaded_plugin("feishu") is record
    assert registry._channels["feishu"] is sentinel


@pytest.mark.asyncio
async def test_python_plugin_reload_to_descriptor_refuses_before_probe_or_swap(
    tmp_path,
    registry,
    monkeypatch,
):
    from qwenpaw.plugins.loader import PluginLoader

    incoming, _manifest = candidate(tmp_path / "incoming")
    old = tmp_path / "installed" / "feishu"
    old.mkdir(parents=True)
    data = manifest_data()
    data["entry"] = {"backend": "plugin.py"}
    old_manifest = PluginManifest.from_dict(data)
    (old / "plugin.json").write_text(json.dumps(data))
    (old / "plugin.py").write_text("legacy bytes")
    record = PluginRecord(old_manifest, old, True, instance=NS())
    loader = PluginLoader([old.parent])
    loader.registry = registry
    loader._loaded_plugins["feishu"] = record
    loader.lifecycle.ensure_instance("feishu")
    before = file_snapshot(tmp_path)
    prohibit_loader_side_effects(loader, monkeypatch)
    result = await loader.reload_plugin_unlocked("feishu", new_source=incoming)
    assert not result.ok and result.unchanged
    assert any(
        "channel_runtime_not_integrated" in error for error in result.errors
    )
    assert loader.get_loaded_plugin("feishu") is record
    assert file_snapshot(tmp_path) == before


def test_nonbuiltin_static_and_class_rows_share_collision_table(
    tmp_path,
    registry,
):
    from qwenpaw.app.channels.base import BaseChannel

    class Legacy(BaseChannel):
        channel = "custom"

    source, manifest = candidate(tmp_path, "custom")
    description = describe(source, manifest)
    static = registry.register_channel_descriptor("custom", description)
    assert registry.get_registered_channels() == {}
    with pytest.raises(ValueError):
        registry.register_channel("legacy", "custom", Legacy)
    registry.unregister_channel("custom", expected=static)
    registry.register_channel("legacy", "custom", Legacy)
    row = registry.get_channel_registration("custom")
    assert row is not None and row.channel_class is Legacy
    assert registry.get_channel_catalog_entry("custom") is row
    with pytest.raises(ValueError):
        registry.register_channel_descriptor("custom", description)


@pytest.mark.parametrize("key", ["feishu", "dingtalk", "console"])
def test_active_class_registration_still_cannot_claim_builtins(registry, key):
    from qwenpaw.app.channels.base import BaseChannel

    class Legacy(BaseChannel):
        channel = key

    with pytest.raises(ValueError):
        registry.register_channel(key, key, Legacy)
    assert registry.get_channel_registration(key) is None


@pytest.mark.asyncio
async def test_force_python_install_over_catalog_refuses_before_callback(
    tmp_path,
    registry,
    monkeypatch,
):
    from qwenpaw.plugins.loader import PluginLoader

    installed, manifest = candidate(tmp_path / "installed")
    loader = PluginLoader([installed.parent])
    loader.registry = registry
    record = await loader.load_plugin(
        manifest,
        installed,
        {"app_id": "saved"},
        activate=False,
    )
    row = registry.get_channel_catalog_entry("feishu")
    instance = loader.lifecycle.get_instance("feishu")
    incoming = tmp_path / "incoming" / "feishu"
    incoming.mkdir(parents=True)
    data = manifest_data()
    data["entry"] = {"backend": "plugin.py"}
    (incoming / "plugin.json").write_text(json.dumps(data))
    (incoming / "plugin.py").write_text("raise AssertionError('imported')")
    before = file_snapshot(tmp_path)
    config_before = dict(instance.config)
    callbacks = []
    prohibit_loader_side_effects(loader, monkeypatch)

    def forbidden_persist(*args, **kwargs):
        raise AssertionError("force replace persisted descriptor settings")

    monkeypatch.setattr(
        "qwenpaw.plugins.settings.persist_plugin_settings",
        forbidden_persist,
    )
    with pytest.raises(RuntimeError, match="channel_runtime_not_integrated"):
        await loader.load_plugin_from_path(
            incoming,
            force=True,
            install_dir=installed.parent,
            before_force_unload=callbacks.append,
        )
    assert not callbacks
    assert file_snapshot(tmp_path) == before
    assert loader.get_loaded_plugin("feishu") is record
    assert registry.get_channel_catalog_entry("feishu") is row
    assert instance.config == config_before


@pytest.mark.asyncio
async def test_legacy_api_normalized_channel_projects_canonical_identity(
    registry,
    monkeypatch,
):
    from qwenpaw.app.channels.base import BaseChannel
    from qwenpaw.app.channels.manager import ChannelManager
    from qwenpaw.plugins.api import PluginApi
    from qwenpaw.plugins.lifecycle import PluginInstance
    from qwenpaw.plugins.workspace_projector import WorkspaceProjector

    class Legacy(BaseChannel):
        channel = "  CuStOm  "

    manager = ChannelManager([])
    manager._process = unused_process
    workspace = NS(
        agent_id="normalized",
        channel_manager=manager,
        _config=NS(channels=NS(custom=NS(enabled=True))),
    )
    registry.projector = WorkspaceProjector(
        live_workspaces=lambda: [workspace],
    )
    monkeypatch.setattr(
        "qwenpaw.plugins.api.get_available_channels",
        lambda: ("custom",),
    )
    current = live_channel()
    monkeypatch.setattr(
        "qwenpaw.app.channels.manager.instantiate_channel",
        lambda *args, **kwargs: current,
    )
    instance = PluginInstance("legacy-owner")
    api = PluginApi("legacy-owner", {})
    api.set_registry(registry)
    api.bind_instance(instance)
    api.register_channel(Legacy)
    row = registry.get_channel_registration("custom")
    assert row is not None and Legacy.channel == "custom"
    await registry.projector.project("channel", "custom", "legacy-owner")
    assert current.starts == 1 and manager.channels == [current]
    assert (await instance.teardown_runtime()).clean
    assert current.stops == 1 and manager.channels == []
    assert registry.get_channel_registration("custom") is None
