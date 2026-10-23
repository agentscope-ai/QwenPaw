# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,unused-argument
# pylint: disable=using-constant-test
"""Backend selection through the real Loader and lifecycle coordinator."""

import json
import os
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.plugins.architecture import PluginType
from qwenpaw.plugins.execution_backend import (
    DefinitionResult,
    PluginDescription,
)
from qwenpaw.plugins.loader import PluginLoader
from qwenpaw.plugins.settings import persist_plugin_settings
from qwenpaw.plugins.workspace_projector import WorkspaceProjector
from qwenpaw.runtime.slash_command_registry import SlashCommandRegistry
from tests.fixtures.plugin_execution.host_metadata_backend import (
    HostMetadataBackend,
)


class DescriptorBackend(HostMetadataBackend):
    """Trusted host adapter using ordinary PluginApi effects."""

    discover_disabled = False

    def __init__(self):
        self.preparations = []
        self.definitions = []

    def describe(self, source_path, manifest):
        payload = json.loads(
            (source_path / manifest.entry.descriptor).read_text(),
        )
        return PluginDescription(manifest, source_path, None, payload)

    async def prepare(self, description, *, allow_install, probe, wheels=()):
        self.preparations.append((allow_install, probe, wheels))
        if description.payload.get("requires_dependency"):
            ready = description.source_path / "dependency.ready"
            if allow_install:
                ready.touch()
            if not ready.exists():
                raise RuntimeError("CUSTOM_DEPENDENCY_MISSING")
        return await self.audit_dependencies(description)

    async def load_definition(
        self,
        description,
        config,
        *,
        saved_definition=None,
    ):
        class Definition:
            def register(self, api):
                command = api.config.get("cmd", "old")
                api.register_slash_command(command, lambda c, a: None)
                if command == "reject":
                    raise RuntimeError("CUSTOM_CONFIG_REJECTED")

        definition = Definition()
        self.definitions.append(definition)
        if config.get("blocked"):
            return DefinitionResult(
                definition,
                enabled=False,
                status="inactive",
                diagnostics=("BACKEND_BLOCKED",),
            )
        if config.get("metadata"):
            return DefinitionResult(
                definition,
                diagnostics=(config["metadata"],),
            )
        return DefinitionResult(definition)

    def registration_scope(self, description):
        return nullcontext()

    async def before_activate(self, description):
        return None

    def validate_update(self, old, candidate, *, in_place):
        return None

    def capture_restore_state(self, record):
        return None

    def restore_state(self, state):
        return None


@pytest.fixture
def host(tmp_path, fresh_registry, monkeypatch):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_config_path",
        lambda: tmp_path / "config.json",
    )
    workspace = SimpleNamespace(
        agent_id="talk",
        plugins=SimpleNamespace(slash_command_registry=SlashCommandRegistry()),
    )
    fresh_registry.projector = WorkspaceProjector(
        live_workspaces=lambda: [workspace],
    )
    fresh_registry.set_workspace_manager(
        SimpleNamespace(agents={"talk": workspace}),
    )
    loader = PluginLoader([tmp_path / "plugins"])
    return loader, workspace.plugins.slash_command_registry


def write_source(loader, *, descriptor=False, requires_dependency=False):
    source = loader.plugin_dirs[0] / "demo"
    source.mkdir(parents=True)
    manifest = {
        "id": "demo",
        "name": "Demo",
        "version": "1.0.0",
        "type": "general",
        "entry": (
            {"descriptor": "definition.json"}
            if descriptor
            else {"backend": "main.py"}
        ),
    }
    (source / "plugin.json").write_text(json.dumps(manifest))
    if descriptor:
        (source / "definition.json").write_text(
            json.dumps({"requires_dependency": requires_dependency}),
        )
        (source / "main.py").write_text(
            "raise AssertionError('descriptor executed Python fallback')\n",
        )
    else:
        (source / "main.py").write_text(
            "class Definition:\n"
            "    def register(self, api):\n"
            "        command = api.config.get('cmd', 'old')\n"
            "        api.register_slash_command(command, lambda c, a: None)\n"
            "        if command == 'reject':\n"
            "            raise RuntimeError('PYTHON_CONFIG_REJECTED')\n"
            "plugin = Definition()\n",
        )
    return source


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "descriptor",
    [False, True],
    ids=["python", "host-descriptor"],
)
async def test_public_lifecycle_uses_selected_backend(host, descriptor):
    loader, commands = host
    backend = DescriptorBackend()
    if descriptor:
        loader.backend_resolver.register_descriptor(
            PluginType.GENERAL,
            backend,
        )
    source = write_source(loader, descriptor=descriptor)
    persist_plugin_settings("demo", config={"cmd": "old"})
    assert [manifest.id for manifest, _ in loader.discover_plugins()] == [
        "demo",
    ]
    records = await loader.load_all_plugins(
        configs={"demo": {"cmd": "old"}},
        activate=True,
    )
    record = records["demo"]
    assert record.status == "active"
    assert commands.names() == ["old"]
    assert record.backend_binding.description.source_path == source
    if descriptor:
        assert record.backend_binding.backend is backend
        # Config rebuilds consume the resolved version, not mutable disk.
        (source / "definition.json").write_text("invalid JSON after selection")
    binding = record.backend_binding

    report = await loader.lifecycle.update_config("demo", {"cmd": "new"})
    assert report.ok
    assert record.backend_binding is binding
    if descriptor:
        (source / "definition.json").write_text("{}")
    assert commands.names() == ["new"]
    assert loader.lifecycle.get_instance("demo").config == {"cmd": "new"}
    assert (await loader.lifecycle.set_enabled("demo", False)).quiescent
    assert commands.names() == []
    assert loader.get_loaded_plugin("demo") is None
    enabled = await loader.lifecycle.set_enabled("demo", True)
    assert enabled.status == "active"
    assert commands.names() == ["new"]

    await loader.lifecycle.set_enabled("demo", False)
    repaired = await loader.repair_dependencies("demo")
    assert repaired.status == "inactive"
    assert not repaired.enabled
    assert commands.names() == []
    if descriptor:
        assert any(
            allow_install for allow_install, _, _ in backend.preparations
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "descriptor",
    [False, True],
    ids=["python", "host-descriptor"],
)
async def test_config_register_failure_restores_previous_effects(
    host,
    descriptor,
):
    loader, commands = host
    if descriptor:
        loader.backend_resolver.register_descriptor(
            PluginType.GENERAL,
            DescriptorBackend(),
        )
    write_source(loader, descriptor=descriptor)
    persist_plugin_settings("demo", config={"cmd": "old"})
    await loader.load_all_plugins(
        configs={"demo": {"cmd": "old"}},
        activate=True,
    )
    report = await loader.lifecycle.update_config("demo", {"cmd": "reject"})
    assert not report.ok
    assert not report.needs_restart
    assert any("CONFIG_REJECTED" in error for error in report.errors)
    assert commands.names() == ["old"]
    assert loader.get_loaded_plugin("demo").status == "active"
    assert loader.lifecycle.get_instance("demo").config == {"cmd": "old"}
    from qwenpaw.config.utils import load_config

    assert load_config().plugins["demo"]["cmd"] == "old"
    assert (await loader.lifecycle.update_config("demo", {"cmd": "retry"})).ok
    assert commands.names() == ["retry"]


@pytest.mark.asyncio
async def test_custom_dependency_failure_is_repairable_without_boot_install(
    host,
):
    loader, commands = host
    backend = DescriptorBackend()
    loader.backend_resolver.register_descriptor(PluginType.GENERAL, backend)
    source = write_source(loader, descriptor=True, requires_dependency=True)
    records = await loader.load_all_plugins(
        configs={"demo": {"cmd": "kept"}},
        activate=True,
    )
    assert records["demo"].status == "failed"
    assert not records["demo"].enabled
    assert any(
        "CUSTOM_DEPENDENCY_MISSING" in item
        for item in records["demo"].diagnostics
    )
    assert commands.names() == []
    assert not (source / "dependency.ready").exists()
    assert not backend.definitions
    repaired = await loader.repair_dependencies("demo")
    assert repaired.status == "active"
    assert (source / "dependency.ready").exists()
    assert commands.names() == ["kept"]
    assert loader.lifecycle.get_instance("demo").config == {"cmd": "kept"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "descriptor",
    [False, True],
    ids=["python", "host-descriptor"],
)
async def test_disabled_boot_does_not_execute_backend(host, descriptor):
    loader, commands = host
    backend = DescriptorBackend()
    if descriptor:
        loader.backend_resolver.register_descriptor(
            PluginType.GENERAL,
            backend,
        )
    source = write_source(
        loader,
        descriptor=descriptor,
        requires_dependency=True,
    )
    if not descriptor:
        (source / "main.py").write_text(
            "raise AssertionError('disabled Python executed')\n",
        )
    assert (
        await loader.load_all_plugins(configs={"demo": {"enabled": False}})
        == {}
    )
    assert commands.names() == []
    assert not backend.definitions
    assert not backend.preparations


@pytest.mark.asyncio
async def test_rediscovery_preserves_loaded_binding_when_descriptor_corrupts(
    host,
):
    loader, commands = host
    loader.backend_resolver.register_descriptor(
        PluginType.GENERAL,
        DescriptorBackend(),
    )
    source = write_source(loader, descriptor=True)
    original = (await loader.load_all_plugins(activate=True))["demo"]
    binding, definition = original.backend_binding, original.instance
    (source / "definition.json").write_text("invalid after discovery")
    current = (await loader.load_all_plugins(activate=True))["demo"]
    assert current is original
    assert (
        current.backend_binding is binding and current.instance is definition
    )
    assert current.status == "active" and current.enabled
    assert loader.lifecycle.get_instance("demo").activated
    assert commands.names() == ["old"]


@pytest.mark.asyncio
async def test_config_rebuild_honors_backend_eligibility_and_reactivates(host):
    from qwenpaw.config.utils import load_config

    loader, commands = host
    loader.backend_resolver.register_descriptor(
        PluginType.GENERAL,
        DescriptorBackend(),
    )
    write_source(loader, descriptor=True)
    await loader.load_all_plugins(activate=True)
    assert (
        await loader.lifecycle.update_config(
            "demo",
            {"cmd": "new", "blocked": True},
        )
    ).ok
    record = loader.get_loaded_plugin("demo")
    assert not record.enabled and record.status == "inactive"
    assert "BACKEND_BLOCKED" in record.diagnostics
    assert not loader.lifecycle.get_instance("demo").activated
    assert commands.names() == []
    assert load_config().plugins["demo"]["enabled"] is True
    assert (
        await loader.lifecycle.update_config(
            "demo",
            {"cmd": "ready", "metadata": "BACKEND_READY"},
        )
    ).ok
    assert record.enabled and record.status == "active"
    assert "BACKEND_READY" in record.diagnostics
    assert "BACKEND_BLOCKED" not in record.diagnostics
    assert commands.names() == ["ready"]


@pytest.mark.asyncio
async def test_failed_config_save_restores_backend_result_metadata(
    host,
    monkeypatch,
):
    loader, commands = host
    loader.backend_resolver.register_descriptor(
        PluginType.GENERAL,
        DescriptorBackend(),
    )
    write_source(loader, descriptor=True)
    previous = {"cmd": "old", "metadata": "PREVIOUS_METADATA"}
    persist_plugin_settings("demo", config=previous)
    record = (
        await loader.load_all_plugins(
            configs={"demo": previous},
            activate=True,
        )
    )["demo"]
    original = (record.enabled, record.status, list(record.diagnostics))

    def fail_save(*args, **kwargs):
        raise OSError("CONFIG_COMMIT_REFUSED")

    with monkeypatch.context() as patch:
        patch.setattr(
            "qwenpaw.plugins.settings.persist_plugin_settings",
            fail_save,
        )
        report = await loader.lifecycle.update_config(
            "demo",
            {"cmd": "new", "blocked": True},
        )
    assert not report.ok and not report.needs_restart
    assert (record.enabled, record.status, record.diagnostics) == original
    assert loader.lifecycle.get_instance("demo").config == previous
    assert commands.names() == ["old"]


def write_channel_source(loader, tmp_path):
    from qwenpaw.plugins.architecture import PluginManifest

    root = Path(__file__).resolve().parents[3]
    source = loader.plugin_dirs[0] / "feishu"
    source.mkdir(parents=True)
    manifest = json.loads(
        (root / "plugins/channel/feishu/plugin.json").read_text(),
    )
    manifest.pop("qwenpaw_version", None)
    (source / "plugin.json").write_text(json.dumps(manifest))
    descriptor = json.loads(
        (root / "plugins/channel/feishu/channel.json").read_text(),
    )
    descriptor["entrypoint"].update(module="fixture_driver", qualname="Driver")
    (source / "channel.json").write_text(json.dumps(descriptor))
    (source / "requirements.txt").write_text("")
    marker = tmp_path / "driver-import-pids"
    driver = (
        root / "tests/fixtures/channel_plugins/shared_process_driver.py"
    ).read_text()
    (source / "fixture_driver.py").write_text(
        "from pathlib import Path\nimport os\n"
        f"with Path({str(marker)!r}).open('a') as marker:\n"
        "    marker.write(str(os.getpid()) + '\\n')\n" + driver,
    )
    return root, source, PluginManifest.from_dict(manifest), marker


@pytest.mark.asyncio
async def test_enabling_registered_channel_prepares_once(
    host,
    tmp_path,
    monkeypatch,
):
    from qwenpaw.app.channels.manager import ChannelManager
    from qwenpaw.config.config import Config
    from qwenpaw.plugins.channel_adapter import ChannelRuntimeSettings

    loader, _ = host
    root, source, parsed, marker = write_channel_source(loader, tmp_path)
    loader.registry.configure_channel_runtime(
        ChannelRuntimeSettings(
            python_executable=sys.executable,
            support_root=root / "src",
            qwenpaw_version="2.2.2b4",
            selected_channels=frozenset({"feishu"}),
        ),
    )
    record = await loader.load_plugin(parsed, source, activate=False)
    assert record.enabled and record.status == "registered"
    assert not loader.lifecycle.get_instance("feishu").activated
    config = Config.model_validate(
        {
            "channels": {
                "console": {"enabled": False},
                "feishu": {
                    "enabled": True,
                    "app_id": "fixture",
                    "app_secret": "fixture",
                },
            },
        },
    )

    async def process(request):
        if False:
            yield None

    workspace = SimpleNamespace(
        agent_id="channel-test",
        workspace_dir=tmp_path / "workspace",
        _config=config,
        stream_query=process,
    )
    workspace.workspace_dir.mkdir()
    workspace.channel_manager = ChannelManager.from_config(
        process,
        config,
        workspace_dir=workspace.workspace_dir,
        defer_process_channels=True,
    )
    workspace.channel_manager.set_workspace(workspace)
    loader.registry.projector = WorkspaceProjector(
        live_workspaces=lambda: [workspace],
    )
    preparations = []
    original_prepare = loader._prepare_channel_candidate

    async def observe_prepare(description, **kwargs):
        preparations.append(kwargs)
        return await original_prepare(description, **kwargs)

    monkeypatch.setattr(loader, "_prepare_channel_candidate", observe_prepare)
    try:
        enabled = await loader.lifecycle.set_enabled("feishu", True)
        assert enabled.status == "active" and enabled.enabled
        assert marker.exists()
        assert (
            await workspace.channel_manager.get_channel("feishu") is not None
        )
        assert len(preparations) == 1
    finally:
        await loader.lifecycle.set_enabled("feishu", False)
        await workspace.channel_manager.stop_all()


@pytest.mark.asyncio
async def test_channel_selection_stays_static_and_uses_real_child_preparation(
    host,
    tmp_path,
    monkeypatch,
):
    from qwenpaw.plugins.channel_adapter import ChannelRuntimeSettings

    loader, _ = host
    root, source, parsed, marker = write_channel_source(loader, tmp_path)
    catalogued = await loader.load_plugin(parsed, source, activate=False)
    assert catalogued.status == "catalogued"
    assert not catalogued.enabled
    assert catalogued.backend_binding is not None
    assert not marker.exists()
    with pytest.raises(RuntimeError, match="channel_runtime_not_integrated"):
        await loader.lifecycle.set_enabled("feishu", True)
    assert not marker.exists()
    await loader.lifecycle.set_enabled("feishu", False)

    loader.registry.configure_channel_runtime(
        ChannelRuntimeSettings(
            python_executable=sys.executable,
            support_root=root / "src",
            qwenpaw_version="2.2.2b4",
            selected_channels=frozenset({"feishu"}),
        ),
    )
    disabled = await loader.load_all_plugins(
        configs={"feishu": {"enabled": False}},
    )
    assert disabled["feishu"].status == "inactive"
    assert not marker.exists()
    enabled = await loader.lifecycle.set_enabled("feishu", True)
    assert enabled.status == "active" and enabled.enabled
    assert loader.registry.get_channel_registration("feishu") is not None
    assert marker.exists()
    assert all(
        int(pid) != os.getpid() for pid in marker.read_text().splitlines()
    )
    assert "fixture_driver" not in sys.modules
    assert (
        await loader.lifecycle.update_config("feishu", {"label": "changed"})
    ).ok
    assert loader.lifecycle.get_instance("feishu").config == {
        "label": "changed",
    }
    with monkeypatch.context() as patch:

        def fail_persist(*args, **kwargs):
            raise OSError("CHANNEL_CONFIG_SAVE_FAILED")

        patch.setattr(
            "qwenpaw.plugins.settings.persist_plugin_settings",
            fail_persist,
        )
        failed = await loader.lifecycle.update_config(
            "feishu",
            {"label": "lost"},
        )
    assert not failed.ok and not failed.needs_restart
    assert any(
        "CHANNEL_CONFIG_SAVE_FAILED" in error for error in failed.errors
    )
    assert loader.get_loaded_plugin("feishu").status == "active"
    assert loader.lifecycle.get_instance("feishu").config == {
        "label": "changed",
    }
    assert loader.registry.get_channel_registration("feishu") is not None
    assert (await loader.lifecycle.set_enabled("feishu", False)).quiescent
    assert loader.registry.get_channel_registration("feishu") is None
    repaired = await loader.repair_dependencies("feishu")
    assert repaired.status == "inactive" and not repaired.enabled
    assert loader.get_loaded_plugin("feishu") is None
