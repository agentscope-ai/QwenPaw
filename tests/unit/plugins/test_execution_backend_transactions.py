# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,unused-argument
"""Execution bindings through real update and recovery transactions."""

import asyncio
import json
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.plugins.architecture import PluginManifest, PluginType
from qwenpaw.plugins.execution_backend import (
    DefinitionResult,
    PluginDescription,
)
from qwenpaw.plugins.loader import PluginLoader
from qwenpaw.plugins.lifecycle import UnloadMode
from qwenpaw.plugins.settings import persist_plugin_settings
from qwenpaw.plugins.updates import marker_path, write_updating_marker
from qwenpaw.plugins.workspace_projector import WorkspaceProjector
from qwenpaw.runtime.slash_command_registry import SlashCommandRegistry
from tests.fixtures.plugin_execution.host_metadata_backend import (
    HostMetadataBackend,
)

KEY = "backend-transaction"


class TransactionBackend(HostMetadataBackend):
    """Host adapter with observable runtime effects and controlled failures."""

    discover_disabled = False
    probe_before_activation = False

    def __init__(self):
        self.events = []
        self.running = {}
        self.block_stop = set()

    def describe(self, source_path, manifest):
        payload = json.loads(
            (source_path / manifest.entry.descriptor).read_text(),
        )
        payload["launcher"] = source_path / "worker"
        return PluginDescription(
            manifest,
            source_path,
            None,
            payload,
            source_identity=payload["identity"],
        )

    async def prepare(self, description, *, allow_install, probe, wheels=()):
        payload = description.payload
        self.events.append(
            ("prepare", payload["identity"], allow_install, probe),
        )
        if probe and payload.get("failure") == "probe":
            raise RuntimeError("CUSTOM_PROBE_FAILED")
        return await self.audit_dependencies(description)

    async def load_definition(
        self,
        description,
        config,
        *,
        saved_definition=None,
    ):
        backend = self
        payload = description.payload
        identity = payload["identity"]
        backend.events.append(("load", identity, description.source_path))

        class Definition:
            def register(self, api):
                api.register_slash_command(
                    identity,
                    lambda *_: payload["launcher"],
                )

                def stop():
                    backend.events.append(("stop", identity))
                    if identity in backend.block_stop:
                        raise RuntimeError("CUSTOM_STOP_INCOMPLETE")
                    backend.running.pop(identity, None)

                api.effect("runtime", None, stop)
                if payload.get("failure") == "register":
                    raise RuntimeError("CUSTOM_REGISTER_FAILED")

                def start():
                    if payload.get("failure") == "start":
                        raise RuntimeError("CUSTOM_START_FAILED")
                    assert payload["launcher"].read_text() == identity
                    backend.running[identity] = (
                        payload["launcher"],
                        dict(api.config),
                    )
                    backend.events.append(
                        ("start", identity, payload["launcher"]),
                    )

                api.register_startup_hook("runtime", start)

        return DefinitionResult(Definition())

    def registration_scope(self, description):
        return nullcontext()

    async def before_activate(self, description):
        return None

    def validate_update(self, old, candidate, *, in_place):
        self.events.append(
            (
                "validate",
                old.payload["identity"],
                candidate.payload["identity"],
            ),
        )
        if in_place:
            raise RuntimeError("CUSTOM_IN_PLACE_REFUSED")

    def capture_restore_state(self, record):
        identity = record.backend_binding.description.payload["identity"]
        self.events.append(("capture", identity))
        return identity

    def restore_state(self, state):
        self.events.append(("restore", state))


@pytest.fixture
def host(tmp_path, fresh_registry, monkeypatch):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_config_path",
        lambda: tmp_path / "config.json",
    )
    commands = SlashCommandRegistry()
    workspace = SimpleNamespace(
        agent_id="talk",
        plugins=SimpleNamespace(slash_command_registry=commands),
    )
    fresh_registry.projector = WorkspaceProjector(lambda: [workspace])
    fresh_registry.set_workspace_manager(
        SimpleNamespace(agents={"talk": workspace}),
    )
    loader = PluginLoader([tmp_path / "plugins"])
    backend = TransactionBackend()
    loader.backend_resolver.register_descriptor(PluginType.GENERAL, backend)
    return loader, backend, commands


def write_source(root, identity="old", *, descriptor=True, failure=None):
    root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": KEY,
        "name": "Transaction",
        "version": "1.0.0" if identity == "old" else "2.0.0",
        "type": "general",
        "entry": (
            {"descriptor": "definition.json"}
            if descriptor
            else {"backend": "main.py"}
        ),
    }
    (root / "plugin.json").write_text(json.dumps(manifest))
    (root / "worker").write_text(identity)
    if descriptor:
        (root / "definition.json").write_text(
            json.dumps({"identity": identity, "failure": failure}),
        )
        (root / "main.py").write_text(
            "raise AssertionError('descriptor Python fallback')\n",
        )
    else:
        (root / "main.py").write_text(
            "from pathlib import Path\n"
            "class Definition:\n"
            "    def register(self, api):\n"
            "        api.register_slash_command('old', lambda *_: 'old')\n"
            "        api.effect('stop evidence', None, lambda:\n"
            "            Path(__file__).with_name('stopped')\n"
            "            .write_text('stop'))\n"
            "plugin = Definition()\n",
        )
    return root


def manifest(root):
    return PluginManifest.from_dict(
        json.loads((root / "plugin.json").read_text()),
    )


async def seed(host, *, descriptor=True):
    loader, backend, commands = host
    source = write_source(loader.plugin_dirs[0] / KEY, descriptor=descriptor)
    persist_plugin_settings(KEY, config={"kept": "config"})
    record = await loader.load_plugin(
        manifest(source),
        source,
        {"kept": "config"},
    )
    assert record.status == "active"
    assert commands.names() == ["old"]
    backend.events.clear()
    return source, record


@pytest.mark.asyncio
@pytest.mark.parametrize("force", [False, True], ids=["reload", "force"])
async def test_custom_backend_update_rebases_launcher_to_installed_source(
    host,
    tmp_path,
    force,
):
    loader, backend, commands = host
    installed, old = await seed(host)
    generation = loader.lifecycle.get_instance(KEY).generation
    candidate = write_source(tmp_path / "candidate", "new")
    if force:
        record = await loader.load_plugin_from_path(candidate, force=True)
    else:
        report = await loader.lifecycle.reload(KEY, new_source=candidate)
        assert report.ok, report.errors
        record = loader.get_loaded_plugin(KEY)
    assert record is not old
    assert record.global_enabled
    assert record.backend_binding.backend is backend
    assert record.backend_binding.description.source_path == installed
    assert record.backend_binding.description.payload["identity"] == "new"
    assert commands.names() == ["new"]
    assert backend.running == {
        "new": (installed / "worker", {"kept": "config"}),
    }
    assert loader.lifecycle.get_instance(KEY).generation == generation + 1
    assert ("validate", "old", "new") in backend.events
    assert [
        event for event in backend.events if event[0] == "prepare" and event[3]
    ] == [("prepare", "new", force, True)]
    assert not marker_path(KEY).exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_type",
    [RuntimeError, asyncio.CancelledError],
    ids=["error", "cancellation"],
)
async def test_force_callback_failure_preserves_old_service_and_propagates(
    host,
    tmp_path,
    error_type,
):
    loader, backend, commands = host
    installed, old = await seed(host)
    binding = old.backend_binding
    instance = loader.lifecycle.get_instance(KEY)
    generation = instance.generation
    settings = (tmp_path / "config.json").read_bytes()
    source_bytes = {
        path.relative_to(installed): path.read_bytes()
        for path in installed.rglob("*")
        if path.is_file()
    }
    candidate = write_source(tmp_path / "candidate", "new")
    callbacks = []

    def reject(plugin_id):
        callbacks.append(("before", plugin_id))
        raise error_type("BEFORE_FORCE_REFUSED")

    with pytest.raises(error_type, match="BEFORE_FORCE_REFUSED"):
        await loader.load_plugin_from_path(
            candidate,
            force=True,
            before_force_unload=reject,
            after_load=lambda record: callbacks.append(("after", record)),
        )
    assert callbacks == [("before", KEY)]
    assert loader.get_loaded_plugin(KEY) is old
    assert old.backend_binding is binding
    assert old.status == "active" and old.global_enabled
    assert loader.lifecycle.get_instance(KEY) is instance
    assert instance.generation == generation
    assert instance.config == {"kept": "config"}
    assert commands.names() == ["old"]
    assert backend.running == {
        "old": (installed / "worker", {"kept": "config"}),
    }
    assert not any(
        event[0] in {"stop", "load", "start"} for event in backend.events
    )
    assert source_bytes == {
        path.relative_to(installed): path.read_bytes()
        for path in installed.rglob("*")
        if path.is_file()
    }
    assert (tmp_path / "config.json").read_bytes() == settings
    assert not marker_path(KEY).exists()
    assert {path.name for path in installed.parent.iterdir()} == {KEY}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "explicit",
    [False, True],
    ids=["delegate", "binding"],
)
async def test_foreign_channel_environment_never_receives_supplied_wheels(
    host,
    tmp_path,
    monkeypatch,
    explicit,
):
    from qwenpaw.plugins.channel_adapter import ChannelRuntimeSettings

    loader, _, _ = host
    root = Path(__file__).resolve().parents[3]
    source = tmp_path / "channel-source"
    source.mkdir()
    for name in ("plugin.json", "channel.json"):
        (source / name).write_bytes(
            (root / "plugins/channel/feishu" / name).read_bytes(),
        )
    (source / "requirements.txt").write_text("")
    loader.registry.configure_channel_runtime(
        ChannelRuntimeSettings(
            sys.executable,
            root / "src",
            "2.2.2b4",
            selected_channels=frozenset({"feishu"}),
            dependency_install_target=tmp_path / "foreign-site",
        ),
    )
    binding = loader.backend_resolver.resolve(source, manifest(source))
    installed = tmp_path / "installed-wheel"
    observed = []
    process = SimpleNamespace(last_cleanup=None)

    async def own_preparation(*args):
        return process

    async def shared_gate(*args, wheels=(), **kwargs):
        observed.append(wheels)
        if wheels:
            installed.touch()
        return "audited"

    monkeypatch.setattr(loader, "_own_preparation", own_preparation)
    monkeypatch.setattr(
        "qwenpaw.plugins.dependency_gate.prepare_shared_dependencies",
        shared_gate,
    )
    if explicit:
        await binding.prepare(
            allow_install=True,
            probe=False,
            wheels=("supplied.whl",),
            owns_dependency_env=False,
        )
    else:
        monkeypatch.setattr(
            loader.lifecycle.delegate,
            "owns_dependency_env",
            lambda *_: False,
        )
        await loader._prepare_channel_candidate(
            binding.description.payload,
            allow_install=True,
            probe=False,
            wheels=("supplied.whl",),
        )
    assert observed == [()]
    assert not installed.exists()
    assert not (tmp_path / "foreign-site").exists()
    assert not (loader.plugin_dirs[0] / "feishu").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["probe", "register", "start"])
async def test_custom_candidate_failure_restores_old_binding_and_runtime(
    host,
    tmp_path,
    failure,
):
    loader, backend, commands = host
    installed, old = await seed(host)
    generation = loader.lifecycle.get_instance(KEY).generation
    candidate = write_source(tmp_path / "candidate", "new", failure=failure)
    report = await loader.lifecycle.reload(KEY, new_source=candidate)
    assert not report.ok and not report.needs_restart
    assert f"CUSTOM_{failure.upper()}_FAILED" in " ".join(report.errors)
    restored = loader.get_loaded_plugin(KEY)
    assert restored.status == "active" and restored.global_enabled
    assert restored.backend_binding.backend is backend
    assert restored.backend_binding.description.source_path == installed
    assert restored.backend_binding.description.payload["identity"] == "old"
    assert restored.manifest.version == "1.0.0"
    assert commands.names() == ["old"]
    assert backend.running == {
        "old": (installed / "worker", {"kept": "config"}),
    }
    assert loader.lifecycle.get_instance(KEY).generation == generation
    assert not marker_path(KEY).exists()
    if failure == "probe":
        assert report.unchanged and restored is old
        assert not any(event[0] == "stop" for event in backend.events)
    else:
        assert ("capture", "old") in backend.events
        assert ("restore", "old") in backend.events
        assert backend.events.index(("restore", "old")) < backend.events.index(
            ("start", "old", installed / "worker"),
        )


@pytest.mark.asyncio
async def test_disabled_descriptor_reinstall_repair_enable_and_uninstall(
    host,
    tmp_path,
):
    loader, backend, commands = host
    installed, _ = await seed(host)
    assert (await loader.lifecycle.set_enabled(KEY, False)).quiescent
    assert loader.get_loaded_plugin(KEY) is None
    candidate = write_source(tmp_path / "candidate", "new")
    backend.events.clear()
    record = await loader.load_plugin_from_path(candidate, force=True)
    assert record.status == "inactive" and not record.enabled
    assert not record.global_enabled
    assert record.backend_binding.backend is backend
    assert record.backend_binding.description.source_path == installed
    assert record.backend_binding.description.payload["identity"] == "new"
    assert commands.names() == [] and not backend.running
    assert not any(
        event[0] in {"prepare", "load", "start"} for event in backend.events
    )
    repaired = await loader.repair_dependencies(KEY)
    assert repaired.status == "inactive" and not repaired.enabled
    assert ("prepare", "new", True, True) in backend.events
    assert commands.names() == [] and not backend.running
    enabled = await loader.lifecycle.set_enabled(KEY, True)
    assert enabled.status == "active"
    assert backend.running == {
        "new": (installed / "worker", {"kept": "config"}),
    }
    assert (await loader.lifecycle.set_enabled(KEY, False)).quiescent
    backend.events.clear()
    report = await loader.unload_plugin(KEY, mode=UnloadMode.UNINSTALL)
    assert report.quiescent and not installed.exists()
    assert not any(
        event[0] in {"prepare", "load", "start"} for event in backend.events
    )


@pytest.mark.asyncio
async def test_prepared_boot_recovery_selects_restored_old_descriptor(
    host,
    tmp_path,
):
    loader, backend, commands = host
    installed = write_source(loader.plugin_dirs[0] / KEY, "new")
    backup = write_source(tmp_path / "backup", "old")
    write_updating_marker(KEY, backup_path=backup, target_path=installed)
    persist_plugin_settings(KEY, config={"kept": "config"})
    await loader.load_all_plugins(
        configs={KEY: {"kept": "config"}},
        activate=True,
    )
    record = loader.get_loaded_plugin(KEY)
    assert record.status == "active"
    assert record.manifest.version == "1.0.0"
    assert record.backend_binding.backend is backend
    assert record.backend_binding.description.source_path == installed
    assert record.backend_binding.description.payload["identity"] == "old"
    assert commands.names() == ["old"]
    assert backend.running == {
        "old": (installed / "worker", {"kept": "config"}),
    }
    assert not any(
        event[0] in {"load", "start"} and event[1] == "new"
        for event in backend.events
    )
    assert not any(
        event[0] == "prepare" and event[2] for event in backend.events
    )
    assert not backup.exists() and not marker_path(KEY).exists()


@pytest.mark.asyncio
async def test_custom_in_place_constraint_runs_before_old_stop(host):
    loader, backend, commands = host
    installed, old = await seed(host)
    report = await loader.lifecycle.reload(KEY)
    assert not report.ok and report.unchanged
    assert "CUSTOM_IN_PLACE_REFUSED" in " ".join(report.errors)
    assert loader.get_loaded_plugin(KEY) is old
    assert commands.names() == ["old"]
    assert backend.running["old"][0] == installed / "worker"
    assert not any(event[0] in {"prepare", "stop"} for event in backend.events)


@pytest.mark.asyncio
async def test_incomplete_old_stop_prevents_source_replacement(host, tmp_path):
    loader, backend, _ = host
    installed, old = await seed(host)
    candidate = write_source(tmp_path / "candidate", "new")
    backend.block_stop.add("old")
    try:
        report = await loader.lifecycle.reload(KEY, new_source=candidate)
        assert not report.ok and report.needs_restart
        assert "CUSTOM_STOP_INCOMPLETE" in " ".join(report.errors)
        assert manifest(installed).version == "1.0.0"
        assert loader.get_loaded_plugin(KEY) is old
        assert loader.lifecycle.get_instance(KEY).has_runtime_ledger()
        assert backend.running["old"][0] == installed / "worker"
        assert not any(
            event[0] == "start" and event[1] == "new"
            for event in backend.events
        )
        assert not marker_path(KEY).exists()
    finally:
        backend.block_stop.clear()
        await loader.unload_plugin(KEY)


@pytest.mark.asyncio
async def test_no_record_residual_owner_prevents_force_directory_replacement(
    host,
    tmp_path,
):
    loader, _, commands = host
    installed = write_source(loader.plugin_dirs[0] / KEY)
    candidate = write_source(tmp_path / "candidate", "new")
    persist_plugin_settings(KEY, enabled=False)
    from qwenpaw.plugins.ownership import RuntimeKey, RuntimeStopReceipt

    owners = loader.registry.runtime_owners
    held = owners.reserve(
        KEY,
        RuntimeKey("worker", "retained", "global"),
        installed,
        instance_id="retained",
    )

    async def stop():
        return RuntimeStopReceipt(False, "worker remains", exited=False)

    owners.attach(held, stop, resource=object())
    try:
        with pytest.raises(RuntimeError, match="STILL_OWNED|restart"):
            await loader.load_plugin_from_path(candidate, force=True)
        assert manifest(installed).version == "1.0.0"
        assert owners.leases(KEY) == (held,)
        assert loader.get_loaded_plugin(KEY) is None
        assert commands.names() == []
        assert not marker_path(KEY).exists()
    finally:
        assert owners.release(held, RuntimeStopReceipt(True))


@pytest.mark.asyncio
async def test_offline_descriptor_install_prepares_without_runtime_effects(
    host,
    tmp_path,
):
    loader, backend, commands = host
    candidate = write_source(tmp_path / "candidate", "new", failure="probe")

    record = await loader.install_plugin_files(candidate)

    installed = loader.plugin_dirs[0] / KEY
    assert record.status == "inactive" and not record.enabled
    assert record.backend_binding.backend is backend
    assert record.source_path == installed
    assert (installed / "worker").read_text() == "new"
    assert backend.events == [("prepare", "new", True, False)]
    assert backend.running == {} and commands.names() == []
    assert not loader.registry.runtime_owners.leases(KEY)
    assert not marker_path(KEY).exists()


@pytest.mark.asyncio
async def test_offline_prepare_failure_preserves_active_source_and_user_files(
    host,
    tmp_path,
    monkeypatch,
):
    loader, backend, commands = host
    installed, old = await seed(host)
    (installed / "user.txt").write_text("keep user content")
    before = {
        path.relative_to(installed): path.read_bytes()
        for path in installed.rglob("*")
        if path.is_file()
    }
    candidate = write_source(tmp_path / "candidate", "new")

    async def fail_prepare(description, *, allow_install, probe, wheels=()):
        assert description.source_path == candidate
        assert allow_install and not probe and wheels == ()
        raise RuntimeError("OFFLINE_PREPARATION_FAILED")

    monkeypatch.setattr(backend, "prepare", fail_prepare)
    with pytest.raises(RuntimeError, match="OFFLINE_PREPARATION_FAILED"):
        await loader.install_plugin_files(candidate, force=True)

    assert {
        path.relative_to(installed): path.read_bytes()
        for path in installed.rglob("*")
        if path.is_file()
    } == before
    assert loader.get_loaded_plugin(KEY) is old
    assert commands.names() == ["old"]
    assert backend.running == {
        "old": (installed / "worker", {"kept": "config"}),
    }
    assert not marker_path(KEY).exists()


@pytest.mark.asyncio
async def test_offline_force_install_cannot_replace_retained_runtime_source(
    host,
    tmp_path,
):
    from qwenpaw.plugins.ownership import RuntimeKey, RuntimeStopReceipt

    loader, _, commands = host
    installed = write_source(loader.plugin_dirs[0] / KEY)
    candidate = write_source(tmp_path / "candidate", "new")
    owners = loader.registry.runtime_owners
    lease = owners.reserve(
        KEY,
        RuntimeKey("worker", "retained-offline", "global"),
        installed,
        instance_id="retained-offline-runtime",
    )

    async def stop():
        return RuntimeStopReceipt(True, "process still alive", exited=False)

    owners.attach(lease, stop, resource=object())
    try:
        with pytest.raises(RuntimeError, match="STILL_OWNED|restart"):
            await loader.install_plugin_files(candidate, force=True)
        assert manifest(installed).version == "1.0.0"
        assert (installed / "worker").read_text() == "old"
        assert owners.leases(KEY) == (lease,)
        assert loader.get_loaded_plugin(KEY) is None
        assert commands.names() == [] and not marker_path(KEY).exists()
    finally:
        assert owners.release(lease, RuntimeStopReceipt(True))


@pytest.mark.asyncio
@pytest.mark.parametrize("incomplete", ["business", "process", "residual"])
async def test_uninstall_preserves_settings_and_artifact_until_owner_stops(
    host,
    tmp_path,
    incomplete,
):
    from qwenpaw.config.utils import load_config
    from qwenpaw.plugins.ownership import RuntimeKey, RuntimeStopReceipt

    loader, _, _ = host
    installed, record = await seed(host)
    artifact = tmp_path / "owned-artifact"
    artifact.write_text("keep until stop receipt")
    instance = loader.lifecycle.get_instance(KEY)
    instance.record_install("owned artifact", artifact.unlink)
    owners = loader.registry.runtime_owners
    lease = owners.reserve(
        KEY,
        RuntimeKey("worker", "untracked-by-ledger", "global"),
        installed,
        instance_id="retained-runtime",
    )
    receipt = {
        "business": RuntimeStopReceipt(False, "business still live"),
        "process": RuntimeStopReceipt(
            True,
            "process still live",
            exited=False,
        ),
        "residual": RuntimeStopReceipt(True, residual=("retained child",)),
    }[incomplete]

    async def stop():
        return receipt

    owners.attach(lease, stop, resource=object())
    try:
        report = await loader.unload_plugin(KEY, mode=UnloadMode.UNINSTALL)
        assert (
            not report.clean and not report.quiescent and report.needs_restart
        )
        assert loader.get_loaded_plugin(KEY) is record
        assert owners.leases(KEY) == (lease,)
        assert (
            installed.exists()
            and artifact.read_text() == "keep until stop receipt"
        )
        assert load_config().plugins[KEY] == {
            "kept": "config",
            "enabled": True,
        }

        receipt = RuntimeStopReceipt(True)
        report = await loader.unload_plugin(KEY, mode=UnloadMode.UNINSTALL)
        assert report.clean and report.quiescent, report.errors
        assert not owners.leases(KEY)
        assert not installed.exists() and not artifact.exists()
        assert KEY not in (load_config().plugins or {})
        assert loader.get_loaded_plugin(KEY) is None
    finally:
        receipt = RuntimeStopReceipt(True)
        await owners.stop(lease)


@pytest.mark.asyncio
async def test_python_reload_honors_explicit_foreign_dependency_ownership(
    host,
    tmp_path,
    monkeypatch,
):
    loader, _, _ = host
    await seed(host, descriptor=False)
    candidate = write_source(tmp_path / "candidate", "new", descriptor=False)

    async def forbidden_install(*args, **kwargs):
        raise AssertionError("foreign dependency environment was modified")

    monkeypatch.setattr(
        loader,
        "_ensure_dependencies_installed",
        forbidden_install,
    )
    async with loader.plugin_lifecycle(KEY):
        report = await loader.reload_plugin_unlocked(
            KEY,
            new_source=candidate,
            owns_dependency_env=False,
        )
    assert report.ok, report.errors


@pytest.mark.asyncio
async def test_python_in_place_rollback_retains_definition_and_imports(
    host,
):
    loader, _, commands = host
    installed = write_source(loader.plugin_dirs[0] / KEY, descriptor=False)
    (installed / "helper.py").write_text("VALUE = 'old'\n")
    (installed / "main.py").write_text(
        "import helper\n"
        "class Definition:\n"
        "    def register(self, api):\n"
        "        api.register_slash_command(\n"
        "            helper.VALUE, lambda *_: helper.VALUE)\n"
        "plugin = Definition()\n",
    )
    old = await loader.load_plugin(manifest(installed), installed)
    original_definition = old.instance
    module_name = "plugin_backend_transaction"
    original_module = sys.modules[module_name]
    original_helper = sys.modules[module_name + ".helper"]
    (installed / "helper.py").write_text("VALUE = 'changed'\n")
    changed_manifest = json.loads((installed / "plugin.json").read_text())
    changed_manifest["version"] = "2.0.0"
    (installed / "plugin.json").write_text(json.dumps(changed_manifest))
    (installed / "main.py").write_text(
        "import helper\n"
        "class Definition:\n"
        "    def register(self, api):\n"
        "        raise RuntimeError('IN_PLACE_REGISTER_FAILED')\n"
        "plugin = Definition()\n",
    )
    report = await loader.lifecycle.reload(KEY)
    assert not report.ok and not report.needs_restart
    assert "IN_PLACE_REGISTER_FAILED" in " ".join(report.errors)
    assert loader.get_loaded_plugin(KEY).instance is original_definition
    assert loader.get_loaded_plugin(KEY).manifest.version == "1.0.0"
    assert commands.names() == ["old"]
    assert sys.modules[module_name] is original_module
    assert sys.modules[module_name + ".helper"] is original_helper
    assert original_helper.VALUE == "old"
    assert str(installed) not in sys.path


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "old_descriptor",
    [False, True],
    ids=["python-to-descriptor", "descriptor-to-python"],
)
async def test_backend_switch_is_refused_before_old_teardown_or_disk_writes(
    host,
    tmp_path,
    old_descriptor,
):
    loader, backend, commands = host
    installed, old = await seed(host, descriptor=old_descriptor)
    before = {
        path.relative_to(installed): path.read_bytes()
        for path in installed.rglob("*")
        if path.is_file()
    }
    generation = loader.lifecycle.get_instance(KEY).generation
    candidate = write_source(
        tmp_path / "candidate",
        "new",
        descriptor=not old_descriptor,
    )
    report = await loader.lifecycle.reload(KEY, new_source=candidate)
    assert not report.ok and report.unchanged
    assert "backend" in " ".join(report.errors).lower()
    assert loader.get_loaded_plugin(KEY) is old
    assert commands.names() == ["old"]
    assert loader.lifecycle.get_instance(KEY).generation == generation
    assert not (installed / "stopped").exists()
    assert not any(event[0] in {"stop", "prepare"} for event in backend.events)
    assert before == {
        path.relative_to(installed): path.read_bytes()
        for path in installed.rglob("*")
        if path.is_file()
    }
    assert not marker_path(KEY).exists()


@pytest.mark.asyncio
async def test_changed_published_identity_is_refused_before_start_and_restored(
    host,
    tmp_path,
    monkeypatch,
):
    loader, backend, commands = host
    installed, _ = await seed(host)
    candidate = write_source(tmp_path / "candidate", "new")
    swap = loader._swap_plugin_dir

    async def tampered_swap(*args, **kwargs):
        backup = await swap(*args, **kwargs)
        (installed / "definition.json").write_text(
            json.dumps({"identity": "unprobed"}),
        )
        (installed / "worker").write_text("unprobed")
        return backup

    monkeypatch.setattr(loader, "_swap_plugin_dir", tampered_swap)
    report = await loader.lifecycle.reload(KEY, new_source=candidate)
    assert not report.ok and not report.needs_restart
    assert "identity" in " ".join(report.errors).lower()
    restored = loader.get_loaded_plugin(KEY)
    assert restored.status == "active"
    assert restored.backend_binding.backend is backend
    assert restored.backend_binding.description.source_path == installed
    assert restored.backend_binding.description.source_identity == "old"
    assert restored.backend_binding.description.payload["identity"] == "old"
    assert manifest(installed).version == "1.0.0"
    assert commands.names() == ["old"]
    assert backend.running == {
        "old": (installed / "worker", {"kept": "config"}),
    }
    assert not any(
        event[0] in {"load", "start"} and event[1] == "unprobed"
        for event in backend.events
    )
    assert not marker_path(KEY).exists()
