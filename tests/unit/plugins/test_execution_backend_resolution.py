# -*- coding: utf-8 -*-
# Pytest fixture injection and real boundary-state checks are intentional.
# pylint: disable=unused-argument
# pylint: disable=redefined-outer-name
"""Independent F1.1 contracts for host-selected execution backends."""

import asyncio
import builtins
import importlib
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from qwenpaw.plugins.architecture import (
    PluginEntryPoints,
    PluginManifest,
    PluginRecord,
    PluginType,
)


@pytest.fixture
def execution():
    """A missing implementation is a deliberate RED, not collection failure."""
    name = "qwenpaw.plugins.execution_backend"
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name != name:
            raise

        def missing(*args, **kwargs):
            pytest.fail(
                "F1.1 execution backend resolver has not been implemented",
                pytrace=False,
            )

        return SimpleNamespace(
            BackendResolver=missing,
            PluginDescription=missing,
        )


class DescribeBackend:
    """Only describe may run during resolution; every executable hook fails."""

    def __init__(self, execution, *, channel=False):
        self.execution = execution
        self.channel = channel
        self.descriptions = []

    def describe(self, source_path, manifest):
        if self.channel:
            from qwenpaw.plugins.channel_adapter import describe_channel

            payload = describe_channel(source_path, manifest)
            requirements_path = payload.requirements_path
        else:
            descriptor = manifest.entry.descriptor
            payload = (
                json.loads((source_path / descriptor).read_text())
                if descriptor
                else {"entry": manifest.entry.backend}
            )
            requirements_path = source_path / "requirements.txt"
        description = self.execution.PluginDescription(
            manifest=manifest,
            source_path=source_path,
            requirements_path=requirements_path,
            payload=payload,
        )
        self.descriptions.append(description)
        return description

    def __getattr__(self, name):
        if name in {
            "prepare",
            "load_definition",
            "before_activate",
            "validate_update",
            "capture_restore_state",
            "restore_state",
        }:

            def forbidden(*args, **kwargs):
                pytest.fail(
                    f"resolution called executable backend hook {name}",
                )

            return forbidden
        raise AttributeError(name)


def manifest(entry=None, *, plugin_type="general", plugin_id="demo"):
    return PluginManifest.from_dict(
        {
            "id": plugin_id,
            "version": "1.0",
            "type": plugin_type,
            "entry": entry or {},
            "meta": {"nested": {"value": "original"}},
        },
    )


@pytest.mark.parametrize("plugin_type", [kind.value for kind in PluginType])
def test_manifest_accepts_descriptor_for_every_known_type(plugin_type):
    parsed = manifest(
        {"descriptor": "definition.json"},
        plugin_type=plugin_type,
    )
    assert parsed.plugin_type == PluginType(plugin_type)
    assert parsed.entry.descriptor == "definition.json"


@pytest.mark.parametrize("plugin_type", [None, "not-a-plugin-type"])
def test_descriptor_still_requires_a_valid_explicit_type(plugin_type):
    raw = {
        "id": "demo",
        "version": "1",
        "entry": {"descriptor": "plugin.json"},
        "meta": {"channel": "feishu"},
    }
    if plugin_type is not None:
        raw["type"] = plugin_type
    with pytest.raises(ValueError, match="(?i)type"):
        PluginManifest.from_dict(raw)


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/plugin.json",
        "../plugin.json",
        "nested/../plugin.json",
        "./plugin.json",
        "nested//plugin.json",
        "plugin\\descriptor.json",
        "C:/plugin.json",
        "plugin.py",
        " plugin.json",
        "plugin.json ",
    ],
)
def test_descriptor_canonical_path_validation_remains_structural(path):
    with pytest.raises(ValueError, match="(?i)(descriptor|path)"):
        manifest({"descriptor": path}, plugin_type="channel")


@pytest.mark.parametrize("legacy", [False, True])
def test_manifest_rejects_backend_descriptor_conflict(legacy):
    raw = {
        "id": "demo",
        "version": "1",
        "type": "channel",
        "entry": {"descriptor": "definition.json"},
    }
    if legacy:
        raw["entry_point"] = "plugin.py"
    else:
        raw["entry"]["backend"] = "plugin.py"
    with pytest.raises(ValueError, match="(?i)(exclusive|conflict|backend)"):
        PluginManifest.from_dict(raw)


def test_legacy_type_inference_and_entry_point_remain_compatible():
    parsed = PluginManifest.from_dict(
        {
            "id": "legacy",
            "version": "1",
            "entry_point": "plugin.py",
            "meta": {"tools": ["legacy_tool"]},
        },
    )
    assert parsed.plugin_type == PluginType.TOOL
    assert parsed.entry.backend == "plugin.py"
    inferred = PluginManifest.from_dict(
        {
            "id": "legacy",
            "version": "1",
            "type": "unknown",
            "entry": {"frontend": "index.js"},
        },
    )
    assert inferred.plugin_type == PluginType.FRONTEND


@pytest.mark.parametrize(
    "entry,plugin_type",
    [
        ({"backend": "plugin.py"}, "tool"),
        ({"backend": "missing.py"}, "channel"),
        ({"frontend": "index.js"}, "frontend"),
        ({}, "general"),
    ],
)
def test_descriptor_free_shapes_bind_python_compatibility_backend(
    execution,
    tmp_path,
    entry,
    plugin_type,
):
    (tmp_path / "plugin.py").write_text(
        "raise AssertionError('must not import')",
    )
    python = DescribeBackend(execution)
    channel = DescribeBackend(execution, channel=True)
    resolver = execution.BackendResolver(python_backend=python)
    resolver.register_descriptor(PluginType.CHANNEL, channel)
    parsed = manifest(entry, plugin_type=plugin_type)
    binding = resolver.resolve(tmp_path, parsed)
    assert binding.backend is python
    assert binding.description is python.descriptions[0]
    assert binding.description.manifest == parsed
    assert binding.description.source_path == tmp_path
    # Preserve exact empty-list checks, including the expected type.
    # pylint: disable-next=use-implicit-booleaness-not-comparison
    assert channel.descriptions == []


def test_host_registered_non_channel_descriptor_uses_its_backend(
    execution,
    tmp_path,
):
    payload = {"implementation": "probe_driver.Driver", "value": [1, 2]}
    (tmp_path / "definition.json").write_text(json.dumps(payload))
    python = DescribeBackend(execution)
    memory = DescribeBackend(execution)
    resolver = execution.BackendResolver(python_backend=python)
    resolver.register_descriptor(PluginType.MEMORY, memory)
    parsed = manifest(
        {"descriptor": "definition.json", "frontend": "index.js"},
        plugin_type="memory",
    )
    binding = resolver.resolve(tmp_path, parsed)
    assert binding.backend is memory
    assert binding.description.payload == payload
    assert (
        binding.description.requirements_path == tmp_path / "requirements.txt"
    )
    # Preserve exact empty-list checks, including the expected type.
    # pylint: disable-next=use-implicit-booleaness-not-comparison
    assert python.descriptions == []


def test_unknown_descriptor_adapter_is_rejected_without_python_fallback(
    execution,
    tmp_path,
):
    # Even executable-looking descriptor data cannot choose host backend code.
    (tmp_path / "definition.json").write_text(
        '{"backend": "probe_driver:Backend"}',
    )
    python = DescribeBackend(execution)
    resolver = execution.BackendResolver(python_backend=python)
    with pytest.raises(ValueError, match="(?i)(memory|descriptor)"):
        resolver.resolve(
            tmp_path,
            manifest({"descriptor": "definition.json"}, plugin_type="memory"),
        )
    # Preserve exact empty-list checks, including the expected type.
    # pylint: disable-next=use-implicit-booleaness-not-comparison
    assert python.descriptions == []


@pytest.mark.parametrize("same_backend", [True, False])
def test_duplicate_registration_is_rejected_and_keeps_original(
    execution,
    tmp_path,
    same_backend,
):
    (tmp_path / "definition.json").write_text('{"version": "original"}')
    first = DescribeBackend(execution)
    second = first if same_backend else DescribeBackend(execution)
    resolver = execution.BackendResolver(
        python_backend=DescribeBackend(execution),
    )
    resolver.register_descriptor(PluginType.MEMORY, first)
    with pytest.raises(ValueError, match="(?i)(registered|duplicate|already)"):
        resolver.register_descriptor(PluginType.MEMORY, second)
    binding = resolver.resolve(
        tmp_path,
        manifest({"descriptor": "definition.json"}, plugin_type="memory"),
    )
    assert binding.backend is first
    if not same_backend:
        # Preserve exact empty-list checks, including the expected type.
        # pylint: disable-next=use-implicit-booleaness-not-comparison
        assert second.descriptions == []


def test_resolver_defensively_rejects_constructed_conflicting_entries(
    execution,
    tmp_path,
):
    python = DescribeBackend(execution)
    memory = DescribeBackend(execution)
    resolver = execution.BackendResolver(python_backend=python)
    resolver.register_descriptor(PluginType.MEMORY, memory)
    parsed = manifest(plugin_type="memory")
    parsed.entry = PluginEntryPoints.model_construct(
        descriptor="definition.json",
        backend="plugin.py",
    )
    with pytest.raises(ValueError, match="(?i)(exclusive|conflict|backend)"):
        resolver.resolve(tmp_path, parsed)
    # Preserve exact empty-list checks, including the expected type.
    # pylint: disable-next=use-implicit-booleaness-not-comparison
    assert python.descriptions == memory.descriptions == []


def test_static_channel_resolution_never_imports_drivers_sdks_or_starts_processes(  # noqa: E501
    execution,
    tmp_path,
    monkeypatch,
):
    from qwenpaw.plugins.channel_adapter import describe_channel

    # Load only the trusted static helper before blocking implementation
    # imports.
    assert callable(describe_channel)
    root = Path(__file__).resolve().parents[3]
    source = tmp_path / "feishu"
    shutil.copytree(root / "plugins/channel/feishu", source)
    parsed = PluginManifest.from_dict(
        json.loads((source / "plugin.json").read_text()),
    )
    python = DescribeBackend(execution)
    channel = DescribeBackend(execution, channel=True)
    resolver = execution.BackendResolver(python_backend=python)
    resolver.register_descriptor(PluginType.CHANNEL, channel)
    original_import = builtins.__import__
    attempts = []

    def guarded_import(name, *args, **kwargs):
        if name.startswith(
            (
                "feishu",
                "dingtalk",
                "lark_oapi",
                "probe_driver",
                "probe_sdk",
                "qwenpaw.app.channels.feishu",
                "qwenpaw.app.channels.dingtalk",
            ),
        ):
            attempts.append(name)
            raise AssertionError(f"static discovery imported {name}")
        return original_import(name, *args, **kwargs)

    def forbidden_process(*args, **kwargs):
        pytest.fail("static discovery started a process")

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(subprocess, "Popen", forbidden_process)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden_process)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", forbidden_process)
    binding = resolver.resolve(source, parsed)
    description = binding.description
    assert binding.backend is channel
    assert description.manifest.id == "feishu"
    assert description.payload.descriptor.channel_key == "feishu"
    assert description.payload.code_root == source.resolve()
    assert description.payload.source_revision
    assert description.requirements_path == source / "requirements.txt"
    # Preserve exact empty-list checks, including the expected type.
    # pylint: disable-next=use-implicit-booleaness-not-comparison
    assert attempts == []
    # Preserve exact empty-list checks, including the expected type.
    # pylint: disable-next=use-implicit-booleaness-not-comparison
    assert python.descriptions == []


def test_binding_snapshots_manifest_and_never_reselects_after_source_changes(
    execution,
    tmp_path,
):
    descriptor = tmp_path / "definition.json"
    descriptor.write_text('{"revision": "old"}')
    python = DescribeBackend(execution)
    memory = DescribeBackend(execution)
    resolver = execution.BackendResolver(python_backend=python)
    resolver.register_descriptor(PluginType.MEMORY, memory)
    parsed = manifest({"descriptor": descriptor.name}, plugin_type="memory")
    binding = resolver.resolve(tmp_path, parsed)
    parsed.version = "2.0"
    parsed.meta["nested"]["value"] = "modified"
    parsed.entry = PluginEntryPoints(backend="plugin.py")
    descriptor.unlink()
    (tmp_path / "plugin.py").write_text("raise AssertionError('not executed')")
    assert binding.backend is memory
    assert binding.description.manifest is not parsed
    assert binding.description.manifest.version == "1.0"
    assert binding.description.manifest.entry.descriptor == "definition.json"
    assert binding.description.manifest.meta["nested"]["value"] == "original"
    assert binding.description.payload == {"revision": "old"}
    # A new source version may select another backend, without changing
    # the old one.
    new_binding = resolver.resolve(tmp_path, parsed)
    assert new_binding.backend is python
    assert binding.backend is memory
    assert len(memory.descriptions) == len(python.descriptions) == 1


@pytest.mark.asyncio
async def test_record_binding_is_internal_and_preserves_public_instance(
    execution,
    tmp_path,
    monkeypatch,
):
    from fastapi.encoders import jsonable_encoder
    from qwenpaw.app.routers import plugins as routes
    from qwenpaw.plugins.loader import _manifest_as_dict

    parsed = manifest({"backend": "plugin.py"}, plugin_type="tool")
    backend = DescribeBackend(execution)
    binding = execution.BackendResolver(python_backend=backend).resolve(
        tmp_path,
        parsed,
    )
    definition = object()
    record = PluginRecord(
        manifest=parsed,
        source_path=tmp_path,
        enabled=True,
        instance=definition,
        backend_binding=binding,
    )
    assert record.backend_binding is binding
    assert record.instance is definition
    legacy_record = PluginRecord(parsed, tmp_path, True, definition)
    assert legacy_record.backend_binding is None
    assert legacy_record.instance is definition
    loader = SimpleNamespace(
        get_all_loaded_plugins=lambda: {parsed.id: record},
    )
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(plugin_loader=loader)),
    )
    monkeypatch.setattr(
        routes,
        "_plugin_config_row",
        lambda plugin_id: {"enabled": True},
    )
    response = jsonable_encoder(await routes.list_plugins(request))
    assert response[0]["id"] == parsed.id
    assert response[0]["plugin_type"] == "tool"
    assert response[0]["enabled"] is True
    assert "backend_binding" not in response[0]
    assert "instance" not in response[0]
    for exposed in (
        response,
        parsed.model_dump(mode="json"),
        _manifest_as_dict(parsed),
    ):
        encoded = json.dumps(exposed)
        assert "backend_binding" not in encoded
        assert "DescribeBackend" not in encoded
        assert "payload" not in encoded
