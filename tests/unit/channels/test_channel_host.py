# -*- coding: utf-8 -*-
"""Host lifecycle through real queues, Agents and child workers."""

import asyncio
import importlib.abc
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import pytest_asyncio

from tests.channel_support.host import (
    Host,
    KEY,
    local_wheel,
    local_certifi_wheel,
    rows,
    texts,
    session_path,
    saved_texts,
)
from tests.channel_support.process import alive, eventually


def _runtime_identity():
    from packaging.markers import default_environment
    from packaging.tags import sys_tags

    environment = default_environment()
    return {
        "version": list(sys.version_info[:2]),
        "implementation": environment["implementation_name"],
        "cache_tag": sys.implementation.cache_tag,
        "sys_platform": environment["sys_platform"],
        "system": environment["platform_system"],
        "machine": environment["platform_machine"],
        "supported_tags": [str(tag) for tag in sys_tags()],
    }


@pytest_asyncio.fixture
async def host(tmp_path, monkeypatch):
    case = await Host.create(tmp_path, monkeypatch)
    yield case
    await case.close()


@pytest.fixture
def static_channel_guard(host, monkeypatch):
    """Guard each discovery/admission run against SDK and worker startup."""
    attempts = []

    class Guard(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.startswith(
                (
                    "lark_oapi",
                    "dingtalk_stream",
                    "qwenpaw_channel_feishu",
                    "qwenpaw_channel_dingtalk",
                    "sample",
                ),
            ):
                attempts.append(fullname)
                raise AssertionError("Static discovery attempted SDK import")

    def forbidden(*args, **kwargs):
        raise AssertionError("Static discovery created a subprocess")

    monkeypatch.setattr(sys, "meta_path", [Guard(), *sys.meta_path])
    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    yield attempts
    assert not attempts and not host.ledger.exists()


def test_official_discovery_and_descriptor_snapshot_are_static(
    host,
    monkeypatch,
    static_channel_guard,
):
    from dataclasses import replace
    from qwenpaw.app.channels.catalog import get_configurable_channel_catalog

    official = get_configurable_channel_catalog()
    assert {
        "console",
        "feishu",
        "dingtalk",
        "telegram",
        "discord",
        "slack",
        "mqtt",
        "mattermost",
        "qq",
        "wecom",
        "yuanbao",
        "xiaoyi",
        "wechat",
        "matrix",
        "imessage",
        "onebot",
        "azure_bot",
        "voice",
        "sip",
    } <= set(official)
    from qwenpaw.channel_protocol.errors import ProtocolValidationError
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.channel_adapter import describe_channel
    from qwenpaw.channel_protocol.shared import validate_channel_contract

    sources = Path(__file__).resolve().parents[3] / "plugins" / "channel"
    descriptors = list(sources.glob("*/channel.json"))
    assert len(descriptors) == 18
    for path in descriptors:
        description = describe_channel(
            path.parent,
            PluginManifest.from_dict(
                json.loads(
                    (path.parent / "plugin.json").read_text(encoding="utf-8"),
                ),
            ),
        )
        assert "channel.generic.v1" in description.descriptor.capabilities
    for key in ("feishu", "dingtalk"):
        with pytest.raises(ProtocolValidationError, match="contract required"):
            validate_channel_contract(key, ())
    from qwenpaw.app.channels.isolated_proxy import IsolatedChannelProxy
    from qwenpaw.channel_protocol.shared import SharedChannelDescriptor

    source = host.artifact(sdk=True)
    description = describe_channel(
        source,
        PluginManifest.from_dict(
            json.loads((source / "plugin.json").read_text(encoding="utf-8")),
        ),
    )
    prepared = description.prepare_proxy_config({"enabled": False})

    def forbid_descriptor_load(*args, **kwargs):
        raise AssertionError("Proxy construction reloaded channel.json")

    with monkeypatch.context() as construction:
        construction.setattr(
            SharedChannelDescriptor,
            "load",
            forbid_descriptor_load,
        )
        proxy = description.create_proxy(
            None,
            prepared.config,
            python_executable=sys.executable,
            support_root=description.code_root,
            instance_id="prepared-descriptor",
            generation=1,
            qwenpaw_version="1.0.0",
            prepared_config=prepared,
        )
        assert proxy.descriptor is description.descriptor
        assert proxy.channel == description.descriptor.channel_key
        configured = IsolatedChannelProxy.from_config(
            None,
            prepared.config,
            launch_spec=proxy._launch_spec,
            descriptor=description.descriptor,
        )
        assert configured.descriptor is description.descriptor
        with pytest.raises(ValueError, match="^IDENTITY_MISMATCH$"):
            IsolatedChannelProxy(
                None,
                launch_spec=replace(
                    proxy._launch_spec,
                    channel_key="different-channel",
                ),
                descriptor=description.descriptor,
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "enabled,runtime",
    [(False, "selected"), (True, None), (True, "unselected")],
)
async def test_channel_catalog_admission_preserves_config_without_runtime(
    host,
    monkeypatch,
    static_channel_guard,
    enabled,
    runtime,
):
    from dataclasses import replace
    from qwenpaw.plugins.settings import persist_plugin_settings
    from qwenpaw.plugins.channel_adapter import (
        ChannelRuntimeNotIntegratedError,
    )

    if runtime is None:
        host.registry.channel_runtime = None
    elif runtime == "unselected":
        host.registry.channel_runtime = replace(
            host.registry.channel_runtime,
            selected_channels=frozenset(),
        )

    source = host.artifact(sdk=True)
    shutil.copytree(source, host.installed)
    persist_plugin_settings(
        KEY,
        enabled=enabled,
        config={"app_id": "saved", "untouched": 7},
    )
    await host.loader.load_all_plugins(types=["channel"], activate=False)
    row = host.registry.get_channel_catalog_entry(KEY)
    assert row is not None and row.global_enabled is enabled
    assert (
        row.description_record.descriptor.config_schema["properties"][
            "app_secret"
        ]["type"]
        == "string"
    )
    record = host.loader.get_loaded_plugin(KEY)
    assert not record.enabled
    assert record.status == ("catalogued" if enabled else "inactive")
    if enabled:
        assert "channel_runtime_not_integrated" in record.diagnostics
        usage = host.registry.dependency_usage
        assert usage.has_declaration(row.dependency_token, plugin_id=KEY)
        (declaration,) = usage.snapshot(
            admission_token=row.dependency_token,
        ).uses
        assert (
            declaration.source_revision
            == row.description_record.source_revision
        )
        assert declaration.requirements == ("sample-shared-sdk==1.0",)
        assert not declaration.pending and declaration.snapshot is None
        with pytest.raises(
            ChannelRuntimeNotIntegratedError,
            match="^channel_runtime_not_integrated$",
        ):
            await host.loader.lifecycle.activate(KEY)
        with pytest.raises(
            ChannelRuntimeNotIntegratedError,
            match="^channel_runtime_not_integrated$",
        ):
            await host.loader.lifecycle.prepare_backend(
                record.backend_binding,
                allow_install=False,
                probe=True,
            )
    from qwenpaw.config.utils import load_config

    assert load_config().plugins[KEY] == {
        "enabled": enabled,
        "app_id": "saved",
        "untouched": 7,
    }


def test_runner_hello_requires_shared_identity():
    from packaging.markers import default_environment
    from qwenpaw.channel_protocol.errors import ProtocolValidationError
    from qwenpaw.channel_protocol.models import validate_method_params

    dedicated = {
        "protocol_version": 1,
        "qwenpaw_version": "1.0.0",
        "channel_key": "feishu",
        "instance_id": "worker",
        "source_revision": "a" * 64,
        "environment_spec_id": "old-spec",
        "environment_id": "old-environment",
        "lock_sha256": "b" * 64,
        "python_abi": "cp311-cp311",
        "platform_tag": "linux_x86_64",
        "capabilities": ["channel.generic.v1"],
    }
    with pytest.raises(ProtocolValidationError):
        validate_method_params("runner.hello", dedicated)
    shared = dict(dedicated)
    for key in ("environment_spec_id", "environment_id", "lock_sha256"):
        shared.pop(key)
    shared.update(
        protocol_version=2,
        dependency_mode="shared",
        generation=1,
        dependencies=[],
        marker_environment=default_environment(),
    )
    assert (
        validate_method_params("runner.hello", shared).to_mapping() == shared
    )

    from qwenpaw.channel_protocol.shared import validate_shared_hello

    expected = {
        name: shared[name]
        for name in (
            "channel_key",
            "instance_id",
            "generation",
            "source_revision",
            "qwenpaw_version",
        )
    }
    expected.update(
        capabilities=("channel.generic.v1",),
        expected_requirements=(),
    )
    assert validate_shared_hello(shared, **expected).to_mapping() == shared
    warning = {
        **shared,
        "dependencies": [
            {
                "requirement": "sample-sdk>=2",
                "name": "sample-sdk",
                "installed_version": "1.0",
                "status": "incompatible",
            },
        ],
    }
    checked = validate_shared_hello(
        warning,
        **{**expected, "expected_requirements": ("sample-sdk>=2",)},
    )
    assert checked.dependencies[0].status == "incompatible"
    for field, value, reason in (
        ("channel_key", "other", "CHANNEL_KEY_MISMATCH"),
        ("instance_id", "old-worker", "INSTANCE_ID_MISMATCH"),
        ("generation", 2, "GENERATION_MISMATCH"),
        ("source_revision", "c" * 64, "SOURCE_REVISION_MISMATCH"),
        ("capabilities", [], "CAPABILITY_MISMATCH"),
    ):
        with pytest.raises(ProtocolValidationError) as rejected:
            validate_shared_hello({**shared, field: value}, **expected)
        assert rejected.value.reason_code == reason
    with pytest.raises(ProtocolValidationError) as rejected:
        validate_shared_hello(
            shared,
            **{**expected, "expected_requirements": ("missing-sdk==1",)},
        )
    assert rejected.value.reason_code == "DEPENDENCY_UNSATISFIED"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["run", "probe"])
@pytest.mark.parametrize(
    "scenario",
    [
        "missing-child",
        "version-warning",
        "missing-extra",
        "unrelated-metadata",
        "installed-url",
        "invalid-metadata",
    ],
)
async def test_channel_worker_checks_declared_dependency_closure(
    host,
    caplog,
    mode,
    scenario,
):
    import logging
    from dataclasses import replace
    from qwenpaw.__version__ import __version__
    from qwenpaw.app.channels.process_supervisor import ChannelProcess
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.channel_adapter import describe_channel

    source = host.artifact(sdk=True)
    selected = "[feature]" if scenario == "missing-extra" else ""
    minimum = "2" if scenario == "version-warning" else "1"
    (source / "requirements.txt").write_text(
        (
            ""
            if scenario == "unrelated-metadata"
            else f"sample-shared-sdk{selected}>={minimum}\n"
        ),
    )
    (host.site / "sample_shared_sdk.py").write_text(
        "def __getattr__(name):\n"
        "    if name != 'VALUE':\n"
        "        raise AttributeError(name)\n"
        "    import qwenpaw_closure_child\n"
        "    return qwenpaw_closure_child.VALUE\n",
    )
    metadata = host.site / "sample_shared_sdk-1.0.dist-info"
    metadata.mkdir()
    child = (
        "qwenpaw-closure-child @ https://example.invalid/child.zip"
        if scenario == "installed-url"
        else f"qwenpaw-closure-child>={minimum}"
    )
    if scenario == "invalid-metadata":
        child = "not a valid dependency declaration ???"
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: sample-shared-sdk\nVersion: 1.0\n"
        f"Requires-Dist: {child}\n"
        "Requires-Dist: qwenpaw-closure-extra; extra == 'feature'\n"
        "Requires-Dist: qwenpaw-closure-inactive; python_version < '0'\n",
    )
    if scenario != "missing-child":
        (host.site / "qwenpaw_closure_child.py").write_text(
            "VALUE = 'offline-sdk'\n",
        )
        metadata = host.site / "qwenpaw_closure_child-1.0.dist-info"
        metadata.mkdir()
        (metadata / "METADATA").write_text(
            "Metadata-Version: 2.1\nName: qwenpaw-closure-child\n"
            "Version: 1.0\n",
        )
    if scenario == "unrelated-metadata":
        external = source.parent / "unrelated-1.0.dist-info"
        external.mkdir()
        (external / "METADATA").write_text(
            "Metadata-Version: 2.1\nName: unrelated\nVersion: 1.0\n",
        )
        (host.site / external.name).symlink_to(
            external,
            target_is_directory=True,
        )
    description = describe_channel(
        source,
        PluginManifest.from_dict(
            json.loads((source / "plugin.json").read_text()),
        ),
    )
    prepared = description.prepare_proxy_config(
        {"enabled": True, "use_sdk": True},
    )
    proxy = description.create_proxy(
        None,
        prepared.config,
        python_executable=sys.executable,
        support_root=Path(__file__).resolve().parents[3] / "src",
        dependency_paths=(host.site,),
        instance_id="closure",
        generation=1,
        qwenpaw_version=__version__,
        prepared_config=prepared,
    )
    spec = replace(proxy._launch_spec, workspace_id="test-workspace")
    process = ChannelProcess()
    for operation in ("get", "put"):
        process.register_method(
            "host.state." + operation,
            lambda params, _request: {"value": params.value},
        )
    caplog.set_level(logging.WARNING, logger="qwenpaw.plugins.worker")
    start = process.start if mode == "run" else process.probe
    try:
        if scenario in {"missing-child", "missing-extra", "invalid-metadata"}:
            with pytest.raises(process.error_type) as rejected:
                await start(spec)
            assert rejected.value.reason_code == (
                "DEPENDENCY_METADATA_INVALID"
                if scenario == "invalid-metadata"
                else "DEPENDENCY_UNSATISFIED"
            )
            assert process.observed_hello is None
            assert process.health_snapshot()["platform_state"] != "connected"
            assert not rows(host.ledger, "connected")
        else:
            await start(spec)
            assert process.observed_hello is not None
            if mode == "run":
                await eventually(lambda: bool(rows(host.ledger, "connected")))
                value = await process.call("sample.identity", {})
                assert value["sdk"] == "offline-sdk"
            else:
                assert not rows(host.ledger, "connected")
            for name in (
                ("sample-shared-sdk", "qwenpaw-closure-child")
                if scenario == "version-warning"
                else ()
            ):
                await eventually(
                    lambda: any(
                        "Dependency warning:" in record.message
                        and name in record.message
                        and "attempting load" in record.message
                        for record in caplog.records
                    ),
                )
    finally:
        stopped = await process.stop()
        assert stopped.exited and not stopped.residual


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["run", "audit", "probe", "manage"])
async def test_execution_preparation_yields_and_consumes_session_snapshot(
    host,
    monkeypatch,
    mode,
):
    import threading
    from dataclasses import replace
    from qwenpaw.__version__ import __version__
    from qwenpaw.app.channels.process_supervisor import ChannelProcess
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.channel_adapter import describe_channel

    source = host.artifact()
    if mode == "manage":
        with (source / "sample.py").open("a") as stream:
            stream.write(
                "\nasync def manage(request):\n"
                "    result = request.to_mapping()\n"
                "    result.pop('parameters')\n"
                "    result.pop('timeout_ms')\n"
                "    return dict(result, outcome='ok', reason_code=None,\n"
                "                result={'scan_url': 'https://example.test/scan',\n"
                "                        'continuation': 'opaque'})\n"
                "Driver.manage = staticmethod(manage)\n",
            )
    description = describe_channel(
        source,
        PluginManifest.from_dict(
            json.loads((source / "plugin.json").read_text()),
        ),
    )
    prepared = description.prepare_proxy_config({"enabled": True})
    identity = _runtime_identity()
    proxy = description.create_proxy(
        None,
        prepared.config,
        python_executable=sys.executable,
        support_root=Path(__file__).resolve().parents[3] / "src",
        instance_id="preparation",
        generation=1,
        qwenpaw_version=__version__,
        prepared_config=prepared,
        runtime_identity=identity,
    )
    spec = replace(proxy._launch_spec, workspace_id="test-workspace")
    process = ChannelProcess()
    entered, release = threading.Event(), threading.Event()
    loop_thread = threading.get_ident()
    read_text, open_worker = Path.read_text, process._open
    metadata = {source / "channel.json", source / "requirements.txt"}
    opened = False

    def read(path, *args, **kwargs):
        if path in metadata:
            assert not opened, "session consumer re-read metadata"
            assert (
                threading.get_ident() != loop_thread
            ), "metadata read on event loop"
            entered.set()
            assert release.wait(5), "preparation barrier was not released"
        return read_text(path, *args, **kwargs)

    async def open_session(*args, **kwargs):
        nonlocal opened
        opened = True
        return await open_worker(*args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setattr(process, "_open", open_session)
    method = {"run": "start", "manage": "start_management"}.get(mode, mode)
    start = getattr(process, method)
    pending = asyncio.create_task(start(spec))
    try:
        await eventually(lambda: entered.is_set() or pending.done())
        if pending.done():
            await pending
        assert entered.is_set()
        assert await asyncio.sleep(0, result="responsive") == "responsive"
        with pytest.raises(process.error_type, match="PROCESS_OWNED"):
            await process.start(spec)
        release.set()
        await pending
        assert opened and process.dependency_snapshot is not None
        snapshot = process.dependency_snapshot
        assert snapshot.supported_tags == tuple(identity["supported_tags"])
        assert type(snapshot).from_mapping(snapshot.to_mapping()) == snapshot
        if mode == "audit":
            assert (
                process.observed_hello is None
            )  # Audit never imports the driver.
        else:
            assert snapshot.to_mapping()["evidence_version"] == 2
            assert (
                process.observed_hello["source_revision"]
                == spec.source_revision
            )
            assert process.observed_hello["generation"] == spec.generation
        if mode == "manage":
            from qwenpaw.channel_protocol.management import MANAGEMENT_METHOD
            from uuid import uuid4

            request = {
                name: getattr(spec, name)
                for name in (
                    "plugin_id",
                    "workspace_id",
                    "channel_key",
                    "instance_id",
                    "generation",
                    "source_revision",
                )
            }
            request.update(
                request_id=str(uuid4()),
                operation="qrcode.fetch",
                timeout_ms=1000,
                parameters={"config": {}},
            )
            unsupported = {
                **request,
                "operation": "connection.verify",
                "parameters": {"config": {}, "level": "reachability"},
            }
            with pytest.raises(
                process.error_type,
                match="MANAGEMENT_UNSUPPORTED",
            ):
                await process.call(MANAGEMENT_METHOD, unsupported)
            result = await process.call(MANAGEMENT_METHOD, request)
            assert result["outcome"] == "ok"
            assert result["result"]["continuation"] == "opaque"
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)
        stopped = await process.stop()
        assert stopped.exited and not stopped.residual


@pytest.mark.asyncio
async def test_channel_probe_rejects_runtime_abi_mismatch(host):
    from qwenpaw.__version__ import __version__
    from qwenpaw.app.channels.process_supervisor import ChannelProcess
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.channel_adapter import describe_channel

    source = host.artifact()
    description = describe_channel(
        source,
        PluginManifest.from_dict(
            json.loads((source / "plugin.json").read_text()),
        ),
    )
    prepared = description.prepare_proxy_config({"enabled": True})
    identity = {**_runtime_identity(), "supported_tags": ["cp999-cp999-any"]}
    proxy = description.create_proxy(
        None,
        prepared.config,
        python_executable=sys.executable,
        support_root=Path(__file__).resolve().parents[3] / "src",
        instance_id="abi-mismatch",
        generation=1,
        qwenpaw_version=__version__,
        prepared_config=prepared,
        runtime_identity=identity,
    )
    process = ChannelProcess()
    try:
        with pytest.raises(process.error_type) as rejected:
            await process.probe(proxy._launch_spec)
        assert (
            rejected.value.reason_code == "CHANNEL_RUNTIME_IDENTITY_MISMATCH"
        )
        assert process.observed_hello is None
        assert not rows(host.ledger, "connected")
    finally:
        stopped = await process.stop()
        assert stopped.exited and not stopped.residual


@pytest.mark.asyncio
async def test_preparation_cancellation_retains_custody_and_rejects_changed_source(
    host,
    monkeypatch,
):
    import threading
    from qwenpaw.__version__ import __version__
    from qwenpaw.app.channels.process_supervisor import ChannelProcess
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.channel_adapter import describe_channel

    source = host.artifact()
    description = describe_channel(
        source,
        PluginManifest.from_dict(
            json.loads((source / "plugin.json").read_text()),
        ),
    )
    prepared = description.prepare_proxy_config({"enabled": True})
    proxy = description.create_proxy(
        None,
        prepared.config,
        python_executable=sys.executable,
        support_root=Path(__file__).resolve().parents[3] / "src",
        instance_id="cancel-preparation",
        generation=1,
        qwenpaw_version=__version__,
        prepared_config=prepared,
    )
    spec, process = proxy._launch_spec, ChannelProcess()
    entered, release = threading.Event(), threading.Event()
    prepare = process._prepare_spec

    def blocked(value):
        entered.set()
        assert release.wait(5), "preparation barrier was not released"
        return prepare(value)

    monkeypatch.setattr(process, "_prepare_spec", blocked)
    pending = asyncio.create_task(process.start(spec))
    try:
        await eventually(entered.is_set)
        pending.cancel()
        stopped = await process.stop(timeout=0.05)
        assert not stopped.exited and "STARTUP_PENDING" in stopped.residual
        assert not pending.done()
        with pytest.raises(process.error_type, match="PROCESS_OWNED"):
            await process.start(spec)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await pending
        stopped = await process.stop()
        assert stopped.exited and not stopped.residual
        assert process._process is None
        code = source / "sample.py"
        original = code.read_text()
        for path, replacement in (
            (code, original + "\n# changed after approval\n"),
            (source / "requirements.txt", "unexpected-dependency==1\n"),
        ):
            previous = path.read_text()
            entered.clear()
            release.clear()
            pending = asyncio.create_task(process.start(spec))
            await eventually(entered.is_set)
            path.write_text(replacement)
            release.set()
            with pytest.raises(
                process.error_type,
                match="^SOURCE_REVISION_MISMATCH$",
            ):
                await pending
            assert process._process is None
            assert process.observed_hello is None
            path.write_text(previous)
            stopped = await process.stop()
            assert stopped.exited and not stopped.residual
        monkeypatch.setattr(process, "_prepare_spec", prepare)
        await process.start(spec)
        assert (
            process.observed_hello["source_revision"] == spec.source_revision
        )
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)
        stopped = await process.stop()
        assert stopped.exited and not stopped.residual


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    ["missing-child", "warning-order", "warning-content", "version"],
)
async def test_channel_preflight_rechecks_metadata_read_during_probe(
    host,
    monkeypatch,
    change,
):
    import zipfile
    from contextlib import nullcontext
    from qwenpaw.app.channels.process_supervisor import ChannelProcess
    from qwenpaw.plugins.dependency_gate import SharedDependencyError

    source = host.artifact(sdk=True)
    wheel = next(local_wheel(host.root / "wheels").glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(host.site)
    metadata = host.site / "sample_shared_sdk-1.0.dist-info/METADATA"
    if change != "missing-child":
        minimum = "1" if change == "version" else "2"
        (source / "requirements.txt").write_text(
            f"sample-warning-child>=2\nsample-shared-sdk>={minimum}\n",
        )
        child = host.site / "sample_warning_child-1.0.dist-info"
        child.mkdir()
        (child / "METADATA").write_text(
            "Metadata-Version: 2.1\nName: sample-warning-child\n"
            "Version: 1.0\n",
        )
        if change == "warning-content":
            with metadata.open("a") as stream:
                stream.write("Requires-Dist: sample-warning-child>=2\n")
    manifest = host.loader.read_source_manifest(source)[1]
    binding = host.loader.backend_resolver.resolve(source, manifest)
    probe = ChannelProcess.probe

    async def changed_after_read(process, spec):
        result = await probe(process, spec)
        if change == "missing-child":
            with metadata.open("a") as stream:
                stream.write("Requires-Dist: new-missing-child>=1\n")
        elif change == "warning-content":
            metadata.write_text(
                metadata.read_text().replace(
                    "sample-warning-child>=2",
                    "sample-warning-child>=3",
                ),
            )
        elif change == "version":
            metadata.write_text(
                metadata.read_text().replace("Version: 1.0", "Version: 1.1"),
            )
        return result

    monkeypatch.setattr(ChannelProcess, "probe", changed_after_read)
    if change == "warning-order":
        expectation = nullcontext()
    elif change == "missing-child":
        expectation = pytest.raises(SharedDependencyError)
    else:
        expectation = pytest.raises(
            RuntimeError,
            match="^DEPENDENCY_ENVIRONMENT_IDENTITY_CHANGED$",
        )
    with expectation as rejected:
        async with host.loader.plugin_lifecycle(KEY):
            await host.loader.lifecycle.preflight_backend(
                binding,
                allow_install=False,
                probe=True,
            )
    if change == "missing-child":
        assert rejected.value.reason_code == "DEPENDENCY_UNSATISFIED"
        assert "new-missing-child" in str(rejected.value)
    assert not host.loader._channel_backend._preparation_scopes


@pytest.mark.asyncio
async def test_channel_worker_preserves_canonical_runtime_context(
    host,
    monkeypatch,
):
    from qwenpaw.constant import WORKING_DIR

    WORKING_DIR.mkdir(parents=True, exist_ok=True)
    (WORKING_DIR / ".env").write_text(
        "CHANNEL_CONTEXT_ENV_PROBE=unexpected\n",
        encoding="utf-8",
    )
    home = host.root / "runtime home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("QWENPAW_WORKING_DIR", "./unresolved-runtime")
    monkeypatch.setenv("QWENPAW_RUNTIME_ID", "channel-context-runtime")
    monkeypatch.delenv("CHANNEL_CONTEXT_ENV_PROBE", raising=False)
    expected_home = str(home) if os.name != "nt" else None
    expected_profile = str(Path.home().resolve()) if os.name == "nt" else None
    media = host.root / "explicit-media"
    ws = await host.workspace("context", media_dir=str(media))
    source = host.artifact()
    shutil.copytree(
        Path(__file__).resolve().parents[3]
        / "plugins/channel/wechat/qwenpaw_channel_wechat",
        source / "qwenpaw_channel_wechat",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    driver = source / "sample.py"
    driver.write_text(
        "import os\n"
        "from pathlib import Path\n"
        "if os.name != 'nt':\n"
        "    import pwd\n"
        "    def missing_user(uid): raise KeyError(uid)\n"
        "    pwd.getpwuid = missing_user\n"
        "from qwenpaw_channel_wechat.platform import WeChatPlatform\n"
        "from qwenpaw.constant import WORKING_DIR\n"
        f"assert WORKING_DIR == Path({str(WORKING_DIR)!r})\n"
        f"assert os.environ['QWENPAW_WORKING_DIR'] == {str(WORKING_DIR)!r}\n"
        "assert os.environ['QWENPAW_RUNTIME_ID'] == 'channel-context-runtime'\n"
        "assert 'CHANNEL_CONTEXT_ENV_PROBE' not in os.environ\n"
        f"assert os.environ.get('HOME') == {expected_home!r}\n"
        f"assert os.environ.get('USERPROFILE') == {expected_profile!r}\n"
        + driver.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    record = await host.loader.load_plugin_from_path(source)
    assert record.status == "active"
    _, value = await host.identity(ws)
    assert value["config"]["workspace_dir"] == str(ws.workspace_dir)
    assert value["config"]["media_dir"] == str(media)
    assert value["config"]["app_secret"] == "local-only"


@pytest.mark.asyncio
async def test_local_install_enable_uses_installed_code_and_offline_dependency(
    host,
    monkeypatch,
):
    from qwenpaw.config.utils import load_config
    from qwenpaw.plugins.settings import persist_plugin_settings

    ws = await host.workspace("first", use_sdk=True)
    source = host.artifact(sdk=True)
    wheels = local_wheel(host.root / "wheels")
    local_certifi_wheel(wheels)
    calls = []

    def offline(command, *, timeout, plugin_id):
        calls.append(command)
        assert (
            command[1:6] == ["-I", "-B", "-m", "pip", "wheel"]
            and plugin_id == KEY
        )
        return subprocess.run(
            [*command, "--no-index", "--find-links", str(wheels)],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )

    monkeypatch.setattr(
        host.loader,
        "_run_subprocess_with_streaming_log",
        offline,
    )
    persist_plugin_settings(KEY, enabled=True, config={"custom": "retained"})
    record = await host.loader.load_plugin_from_path(source)
    assert record.status == "active" and calls
    channel, value = await host.identity(ws)
    assert value["sdk"] == "offline-sdk"
    assert Path(value["source"]).is_relative_to(host.installed)
    assert channel._launch_spec.code_root == host.installed
    assert load_config().plugins[KEY] == {
        "enabled": True,
        "custom": "retained",
    }
    assert (host.site / "sample_shared_sdk.py").is_file() and source.exists()


@pytest.mark.asyncio
async def test_real_agent_stream_final_reply_and_saved_session(
    host,
    monkeypatch,
):
    from qwenpaw.app.channels.process_supervisor import ChannelProcess

    real_probe, probes = ChannelProcess.probe, []

    async def probe(process, *args, **kwargs):
        probes.append(process)
        return await real_probe(process, *args, **kwargs)

    monkeypatch.setattr(ChannelProcess, "probe", probe)
    ws = await host.workspace("actual-agent", streaming_enabled=True)
    await host.real_agent(ws)
    record = await host.loader.load_plugin_from_path(host.artifact())
    assert record.status == "active"
    assert len(probes) == 1
    channel, value = await host.identity(ws)
    assert value["pid"] != os.getpid()
    ack = await host.emit(ws, text="native input", room="conversation")
    assert ack["accepted_event_ids"] == ["one"]
    await eventually(lambda: bool(rows(host.ledger, "finished")))
    assert len(ws.requests) == len(ws.model_calls) == len(ws.builds) == 1
    assert ws.model_calls[0]["pid"] == ws.builds[0]["pid"] == os.getpid()
    request = ws.requests[0]
    assert (request.channel, request.session_id, request.user_id) == (
        KEY,
        "conversation",
        "alice",
    )
    assert request.input[0].content[0].text == "native input"
    assert [
        text
        for message in ws.model_calls[0]["messages"]
        if message.role == "user"
        for text in texts(message.model_dump())
    ] == ["native input"]
    sends = rows(host.ledger, "sent")
    assert sends and all(
        row["pid"] == value["pid"] and row["room"] == "conversation"
        for row in sends
    )
    assert sends[0]["operation"] == "stream.start"
    assert {row["operation"] for row in sends[1:-1]} == {"stream.delta"}
    assert sends[-1]["operation"] == "stream.end"
    assert sends[-1]["text"] == "actual agent answer"
    assert await saved_texts(ws, "conversation") == [
        "native input",
        "actual agent answer",
    ]
    assert len(await ws.chat_manager.list_chats(channel=KEY)) == 1
    assert (
        channel.channel_process.health_snapshot()["platform_state"]
        == "connected"
    )


@pytest.mark.asyncio
async def test_workspace_messages_sessions_reply_targets_and_acl_are_isolated(
    host,
    monkeypatch,
):
    from qwenpaw.app.channels.access_control import get_access_control_store

    one = await host.workspace("one")
    two = await host.workspace("two", access_control_dm=True)
    # Real workspace ACL gates the queue before the process handler is called.
    get_access_control_store(two.workspace_dir).add_to_whitelist(KEY, "alice")
    get_access_control_store(two.workspace_dir).add_to_blacklist(
        KEY,
        "blocked",
    )
    import threading
    from qwenpaw.app.channels.access_control import AccessControlStore

    loop_thread = threading.get_ident()
    decide = AccessControlStore.check_or_add_pending
    decisions = []

    def checked_decision(store, *args, **kwargs):
        assert threading.get_ident() != loop_thread
        result = decide(store, *args, **kwargs)
        decisions.append(result)
        return result

    monkeypatch.setattr(
        AccessControlStore,
        "check_or_add_pending",
        checked_decision,
    )
    await host.real_agent(one, reply="answer:one")
    await host.real_agent(two, reply="answer:two")
    await host.loader.load_plugin_from_path(host.artifact())
    identities = [await host.identity(ws) for ws in (one, two)]
    assert len({value["pid"] for _, value in identities}) == 2
    assert (
        len({value["identity"]["instance_id"] for _, value in identities}) == 2
    )
    await host.emit(one, "one", room="one-room", text="first")
    await host.emit(two, "two", room="two-room", text="second")
    await host.emit(two, "denied", sender="blocked", room="blocked-room")
    await host.emit(two, "pending", sender="new-user", room="pending-room")
    for ws in (one, two):
        assert await ws.channel_manager._queue_manager.drain()
    assert [request.input[0].content[0].text for request in one.requests] == [
        "first",
    ]
    assert [request.input[0].content[0].text for request in two.requests] == [
        "second",
    ]
    sent = [
        row
        for row in rows(host.ledger, "sent")
        if list(texts(row["content_parts"]))
        in (["answer:one"], ["answer:two"])
    ]
    assert {(row["room"], row["pid"]) for row in sent} == {
        ("one-room", identities[0][1]["pid"]),
        ("two-room", identities[1][1]["pid"]),
    }
    assert {
        chat.session_id
        for chat in await one.chat_manager.list_chats(channel=KEY)
    } == {"one-room"}
    assert {
        chat.session_id
        for chat in await two.chat_manager.list_chats(channel=KEY)
    } == {"two-room"}
    assert {"allow", "blocked", "pending"} <= set(decisions)
    pending = get_access_control_store(two.workspace_dir).get_all_pending()
    assert [entry["user_id"] for entry in pending] == ["new-user"]
    assert not session_path(two, "pending-room", "new-user").exists()
    for ws, room, input_text in (
        (one, "one-room", "first"),
        (two, "two-room", "second"),
    ):
        assert (
            len(ws.model_calls) == 1
            and ws.model_calls[0]["pid"] == os.getpid()
        )
        assert await saved_texts(ws, room) == [
            input_text,
            "answer:" + ws.agent_id,
        ]
        assert not session_path(ws, "blocked-room", "blocked").exists()


@pytest.mark.asyncio
async def test_config_read_save_restart_preserves_fields_and_exits_old_worker(
    host,
):
    from qwenpaw.config.config import load_agent_config, save_agent_config

    ws = await host.workspace("configured")
    await host.loader.load_plugin_from_path(host.artifact())
    old, before = await host.identity(ws)
    read = load_agent_config(ws.agent_id)
    read.channels.feishu.app_id = "new-app"
    save_agent_config(ws.agent_id, read)
    ws._config = load_agent_config(ws.agent_id)
    await ws.channel_manager.replace_channel(KEY, ws._config)
    fresh, after = await host.identity(ws)
    assert not alive(before["pid"]) and after["pid"] != before["pid"]
    assert fresh._launch_spec.generation > old._launch_spec.generation
    assert after["config"]["app_id"] == "new-app"
    assert after["config"]["app_secret"] == "local-only"


@pytest.mark.asyncio
@pytest.mark.parametrize("dependency_change", [False, True])
async def test_update_replaces_worker_and_preserves_data(
    host,
    monkeypatch,
    dependency_change,
):
    ws = await host.workspace("updating", use_sdk=dependency_change)
    first = host.artifact(sdk=dependency_change)
    if dependency_change:
        import zipfile

        old_wheel = next(
            local_wheel(
                host.root / "old-wheel",
                version="0.5",
                value="old-sdk",
            ).glob("*.whl"),
        )
        with zipfile.ZipFile(old_wheel) as archive:
            archive.extractall(host.site)
        (first / "requirements.txt").write_text("sample-shared-sdk==0.5\n")
    await host.loader.load_plugin_from_path(first)
    await host.loader.lifecycle.update_config(KEY, {"custom": "keep"})
    old, before = await host.identity(ws)
    data = ws.workspace_dir / "business.json"
    data.write_text('{"retained":true}')
    candidate = host.artifact("2.0.0", sdk=dependency_change)
    if dependency_change:
        from qwenpaw.plugins.dependency_upgrade import (
            DependencyUpgradeRequired,
            dependency_upgrades,
            install_with_upgrade,
        )

        wheels = local_wheel(host.root / "new-wheel")
        local_certifi_wheel(wheels)
        calls = []

        def offline(command, **kwargs):
            calls.append(command)
            return subprocess.run(
                [*command, "--no-index", "--find-links", str(wheels)],
                capture_output=True,
                text=True,
                check=False,
                timeout=kwargs["timeout"],
            )

        monkeypatch.setattr(
            host.loader,
            "_run_subprocess_with_streaming_log",
            offline,
        )
        with pytest.raises(DependencyUpgradeRequired) as review:
            await install_with_upgrade(host.loader, candidate, force=True)
        manager = dependency_upgrades(host.loader)
        operation = manager._read(review.value.operation["id"])
        assert operation["force"] and not operation["requires_restart"]
        assert (
            len(calls) == 1
        )  # The staged replacement retains the successful wheels.
        assert alive(before["pid"])
        assert (await host.identity(ws))[1]["sdk"] == "old-sdk"
        result = await manager.apply(operation["id"])
        assert result["status"] == "succeeded", result
    else:
        report = await host.loader.lifecycle.reload(KEY, new_source=candidate)
        assert report.ok, report.errors
    fresh, after = await host.identity(ws)
    assert not alive(before["pid"]) and after["version"] == "2.0.0"
    assert fresh._launch_spec.generation > old._launch_spec.generation
    assert Path(after["source"]).is_relative_to(host.installed)
    connections = rows(host.ledger, "connected")
    stopped = rows(host.ledger, "stopped")
    assert max(
        row["time"] for row in stopped if row["version"] == "1.0.0"
    ) < min(row["time"] for row in connections if row["version"] == "2.0.0")
    await host.emit(ws, room="updated")
    await eventually(
        lambda: any(
            row["version"] == "2.0.0" for row in rows(host.ledger, "sent")
        ),
    )
    assert host.loader.lifecycle.get_instance(KEY).config == {"custom": "keep"}
    assert data.read_text() == '{"retained":true}'


@pytest.mark.asyncio
async def test_disable_reenable_uninstall_reaps_only_owned_resources(host):
    ws = await host.workspace("lifecycle")
    await host.loader.load_plugin_from_path(host.artifact())
    _, before = await host.identity(ws)
    business = ws.workspace_dir / "business.json"
    business.write_text("keep")
    user_config = ws.workspace_dir / "agent.json"
    config_before = user_config.read_bytes()
    await host.loader.lifecycle.set_enabled(KEY, False)
    assert (
        not alive(before["pid"])
        and await ws.channel_manager.get_channel(KEY) is None
    )
    await host.loader.lifecycle.set_enabled(KEY, True)
    _, fresh = await host.identity(ws)
    assert fresh["pid"] != before["pid"]
    report = await host.loader.unload_plugin(KEY, delete_files=True)
    assert report.clean and report.quiescent
    assert not alive(fresh["pid"]) and not host.registry.runtime_owners.leases(
        KEY,
    )
    assert await ws.channel_manager.get_channel(KEY) is None
    assert business.read_text() == "keep"
    assert not host.installed.exists()
    assert user_config.read_bytes() == config_before
    assert (
        json.loads(user_config.read_text())["channels"][KEY]["app_secret"]
        == "local-only"
    )


@pytest.mark.asyncio
async def test_application_shutdown_reaps_workers_and_preserves_installed_code(
    host,
):
    workspaces = [await host.workspace(name) for name in ("first", "second")]
    await host.loader.load_plugin_from_path(host.artifact())
    pids = [(await host.identity(ws))[1]["pid"] for ws in workspaces]
    from qwenpaw.plugins.lifecycle import UnloadMode

    reports = await host.loader.lifecycle.unload_all(UnloadMode.SHUTDOWN)
    assert reports and all(report.quiescent for report in reports)
    assert all(not alive(pid) for pid in pids)
    assert not host.registry.runtime_owners.leases(KEY)
    assert (host.installed / "sample.py").is_file()
    assert all(
        [
            await ws.channel_manager.get_channel(KEY) is None
            for ws in workspaces
        ],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    ["failed", "disconnected", "exited", "timeout"],
)
async def test_connection_failure_logs_actual_state_without_changing_refusal(
    host,
    caplog,
    failure,
):
    import logging
    from dataclasses import replace

    caplog.set_level(logging.INFO, logger="qwenpaw.plugins.startup")
    host.registry.channel_runtime = replace(
        host.registry.channel_runtime,
        connection_timeout=0.2 if failure == "timeout" else None,
    )
    await host.workspace("diagnostic")
    source = host.artifact(fail_start=failure == "failed")
    if failure != "failed":
        code = source / "sample.py"
        injected = {
            "disconnected": 'await self._context.set_platform_state("disconnected")',
            "exited": "os._exit(23)",
            "timeout": "pass",
        }[failure]
        code.write_text(
            code.read_text().replace(
                "    async def start(self, config):\n",
                "    async def start(self, config):\n"
                f"        {injected}\n"
                "        import asyncio\n"
                "        await asyncio.sleep(2)\n",
            ),
        )
    with pytest.raises(Exception) as refused:
        await host.loader.load_plugin_from_path(source)
    if failure != "timeout":
        assert "CHANNEL_NOT_CONNECTED" in str(refused.value)

    def observed():
        return [
            json.loads(record.getMessage().partition(" ")[2])
            for record in caplog.records
            if record.name == "qwenpaw.plugins.startup"
        ]

    await eventually(
        lambda: any(row["event"] == "connection_failed" for row in observed()),
    )
    if failure == "exited":
        await eventually(
            lambda: any(row["event"] == "worker_exited" for row in observed()),
        )
    events = observed()
    event = next(row for row in events if row["event"] == "connection_failed")
    assert event["plugin_id"] == KEY and event["instance_id"]
    assert event["generation"] >= 1 and event["elapsed_ms"] >= 0
    if failure in {"failed", "disconnected"}:
        assert event["health"]["platform_state"] == failure
    elif failure == "timeout":
        assert event["reason"] == "timeout"
        assert event["health"]["platform_state"] == "connecting"
    else:
        assert any(
            row["event"] == "worker_exited" and row["returncode"] == 23
            for row in events
        )


@pytest.mark.asyncio
async def test_failed_worker_update_restores_usable_source_and_config(host):
    ws = await host.workspace("rollback")
    await host.loader.load_plugin_from_path(host.artifact())
    await host.loader.lifecycle.update_config(KEY, {"custom": "keep"})
    _, before = await host.identity(ws)
    source = (host.installed / "sample.py").read_bytes()
    report = await host.loader.lifecycle.reload(
        KEY,
        new_source=host.artifact("2.0.0", fail_start=True),
    )
    assert not report.ok and report.errors
    failed = rows(host.ledger, "start_failed")[0]
    assert failed["version"] == "2.0.0" and not alive(failed["pid"])
    _, after = await host.identity(ws)
    assert after["version"] == "1.0.0" and not alive(before["pid"])
    assert after["config"] == before["config"]
    assert (host.installed / "sample.py").read_bytes() == source
    assert host.loader.lifecycle.get_instance(KEY).config == {"custom": "keep"}
    await host.emit(ws, room="restored")
    await eventually(lambda: bool(rows(host.ledger, "finished")))
    assert rows(host.ledger, "sent")[-1]["room"] == "restored"


@pytest.mark.asyncio
async def test_pending_host_state_stop_blocks_replacement_until_cleanup(host):
    ws = await host.workspace("blocked-stop")
    await host.loader.load_plugin_from_path(host.artifact())
    channel, before = await host.identity(ws)
    source = (host.installed / "sample.py").read_bytes()
    await channel._state_lock.acquire()
    try:
        report = await host.loader.lifecycle.reload(
            KEY,
            new_source=host.artifact("2.0.0"),
        )
        assert not report.ok and report.needs_restart
        assert (host.installed / "sample.py").read_bytes() == source
        assert not any(
            row["version"] == "2.0.0" for row in rows(host.ledger, "connected")
        )
        assert host.registry.runtime_owners.leases(KEY)
    finally:
        channel._state_lock.release()
    cleanup = await host.loader.unload_plugin(KEY)
    assert cleanup.quiescent and not alive(before["pid"])
    assert not host.registry.runtime_owners.leases(KEY)


@pytest.mark.asyncio
async def test_authorized_external_project_snapshot_delivers_exact_bytes(host):
    from qwenpaw.agents.tools.send_file import send_file_to_user
    from qwenpaw.utils.media_paths import local_media_path
    from qwenpaw.config.context import (
        current_workspace_dir,
        current_project_dir,
    )

    ws = await host.workspace("media")
    await host.loader.load_plugin_from_path(host.artifact())
    channel, identity = await host.identity(ws)
    project = host.root / "project"
    project.mkdir()
    source = project / "report.bin"
    source.write_bytes(b"project attachment\x00\xff")
    workspace_token = current_workspace_dir.set(ws.workspace_dir)
    project_token = current_project_dir.set(project)
    try:
        result = await send_file_to_user("report.bin")
    finally:
        current_project_dir.reset(project_token)
        current_workspace_dir.reset(workspace_token)
    url = str(result.content[0].source.url)
    assert Path(local_media_path(url)).is_relative_to(
        ws.workspace_dir / "media" / "outbound",
    )
    source.write_bytes(b"changed after staging")
    await channel.send_media("recipient", {"type": "file", "file_url": url})
    sent = rows(host.ledger, "sent")
    assert sent[-1]["pid"] == identity["pid"]
    assert sent[-1]["files"] == [b"project attachment\x00\xff".hex()]


@pytest.mark.asyncio
async def test_real_approval_card_and_inbound_operator_decision(
    host,
    monkeypatch,
):
    from qwenpaw.app.approvals import service
    from qwenpaw.app.approvals.models import ApprovalRequestSummary
    from qwenpaw.app.approvals.service import ApprovalIdentityPolicy
    from qwenpaw.app.channels.access_control import get_access_control_store
    from qwenpaw.runtime.builtin_commands import collect_builtin_command_specs
    from qwenpaw.security.tool_guard.approval import ApprovalDecision

    approvals = service.ApprovalService()
    monkeypatch.setattr(service, "_approval_service", approvals)
    ws = await host.workspace("approval", access_control_dm=True)
    get_access_control_store(ws.workspace_dir).add_to_whitelist(KEY, "alice")
    get_access_control_store(ws.workspace_dir).add_to_whitelist(KEY, "bob")
    await host.real_agent(ws)
    for spec in collect_builtin_command_specs():
        ws.plugins.slash_command_registry.register(spec)
    await host.loader.load_plugin_from_path(host.artifact())
    channel, identity = await host.identity(ws)
    pending = await approvals.create_pending_summary(
        session_id="room",
        root_session_id="room",
        owner_agent_id=ws.agent_id,
        user_id="alice",
        channel=KEY,
        agent_id=ws.agent_id,
        summary=ApprovalRequestSummary(
            "test",
            "send_file",
            result_summary="approve",
        ),
        extra={"_channel_instance": channel},
        identity_policy=ApprovalIdentityPolicy.EXACT_REQUESTER,
    )
    await eventually(
        lambda: any(row.get("approval") for row in rows(host.ledger, "sent")),
    )
    card = next(
        row for row in rows(host.ledger, "sent") if row.get("approval")
    )
    assert card["pid"] == identity["pid"]
    assert card["approval"]["request_id"] == pending.request_id
    command = "/approve " + pending.request_id
    await host.emit(ws, "blocked", sender="intruder", text=command)
    assert await ws.channel_manager._queue_manager.drain()
    assert not pending.future.done() and not ws.requests
    await host.emit(ws, "wrong-operator", sender="bob", text=command)
    assert await ws.channel_manager._queue_manager.drain()
    assert not pending.future.done()
    assert ws.requests[-1].user_id == "bob"
    await host.emit(ws, "approved", text=command)
    assert await ws.channel_manager._queue_manager.drain()
    assert pending.future.done()
    assert pending.future.result() is ApprovalDecision.APPROVED
    assert ws.requests[-1].user_id == "alice" and not ws.model_calls


@pytest.fixture
def legacy_start(request, host, tmp_path, monkeypatch):
    from dataclasses import replace
    from types import SimpleNamespace
    from qwenpaw.app.channels.manager import ChannelManager
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.channel_adapter import describe_channel
    from qwenpaw.plugins import azure_legacy

    key = request.param
    root = Path(__file__).resolve().parents[3]
    source = root / "plugins" / "channel" / key
    description = describe_channel(
        source,
        PluginManifest.from_dict(
            json.loads((source / "plugin.json").read_text(encoding="utf-8")),
        ),
    )
    settings = replace(
        host.registry.channel_runtime,
        selected_channels=frozenset({key}),
    )
    row = host.registry.register_channel_descriptor(
        description.plugin_id,
        description,
        runtime_settings=settings,
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", legacy)
    values = (
        {"enabled": True, "app_id": "app", "app_password": "secret"}
        if key == "azure_bot"
        else {
            "enabled": True,
            "homeserver": "https://matrix.test",
            "user_id": "@alice:matrix.test",
            "password": "secret",
        }
    )
    config = {
        "channels": {key: values},
        "agents": {"profiles": {"default": {"workspace_dir": str(workspace)}}},
    }
    config_path = legacy / "config.json"
    config_path.write_text(json.dumps(config))
    reader = azure_legacy
    reader_name = "_snapshot"
    filename = "azure_bot_refs.json"
    state = {"room": {"service_url": "https://bot.test"}}
    (legacy / filename).write_text(json.dumps(state))
    capture_fn = azure_legacy.capture_azure_legacy
    capture = capture_fn(
        config_path=config_path,
        legacy_state_dir=legacy,
        working_dir=legacy,
    )
    field = "legacy_reference_owner"
    manager = ChannelManager([])
    manager._workspace_dir = workspace
    manager._workspace_config = SimpleNamespace(channels={key: values})
    manager._process = lambda _: None

    async def start(channel):
        pass

    monkeypatch.setattr(manager, "_start_owned", start)
    yield SimpleNamespace(
        key=key,
        manager=manager,
        reader=reader,
        reader_name=reader_name,
        field=field,
        capture=capture,
        registry=host.registry,
        row=row,
    )
    for channel in manager.channels:
        manager._release_unstarted(channel)
    manager.channels.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "legacy_start",
    ["azure_bot"],
    indirect=True,
)
async def test_legacy_start_preparation_yields_and_keeps_authorization(
    legacy_start,
    monkeypatch,
):
    import threading

    case = legacy_start
    loop_thread = threading.get_ident()
    calls, reserve_threads = [], []
    original_reserve = case.registry.runtime_owners.reserve

    def reserve(*args, **kwargs):
        reserve_threads.append(threading.get_ident())
        return original_reserve(*args, **kwargs)

    monkeypatch.setattr(case.registry.runtime_owners, "reserve", reserve)
    entered, release = threading.Event(), threading.Event()
    original = getattr(case.reader, case.reader_name)

    def slow(*args, **kwargs):
        calls.append(threading.get_ident())
        entered.set()
        assert release.wait(2), "event loop could not release legacy reader"
        return original(*args, **kwargs)

    monkeypatch.setattr(case.reader, case.reader_name, slow)
    task = asyncio.create_task(
        case.manager._start_one_unlocked(
            case.key,
            case.manager._workspace_config,
        ),
    )
    try:
        await asyncio.wait_for(asyncio.to_thread(entered.wait, 2), 3)
        assert entered.is_set() and not task.done()
        release.set()
        await task
        authorization = case.manager.channels[0]._launch_spec.config[
            case.field
        ]
        assert authorization["capture_id"] == case.capture["capture_id"]
        assert authorization["owner"]["workspace_dir"] == str(
            case.manager._workspace_dir,
        )
        digest_key = "refs_sha256"
        captured = case.capture["entries"][0]
        assert authorization[digest_key] == captured[digest_key]
        assert calls and all(thread != loop_thread for thread in calls)
        assert len(calls) == 1
        assert reserve_threads == [loop_thread]
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "legacy_start,action",
    [
        ("azure_bot", "cancel"),
        ("azure_bot", "disable"),
        ("azure_bot", "unregister"),
        ("azure_bot", "mutate"),
        ("azure_bot", "replace"),
        ("azure_bot", "publish"),
    ],
    indirect=["legacy_start"],
)
async def test_legacy_preparation_does_not_publish_stale_start(
    legacy_start,
    monkeypatch,
    action,
):
    import threading

    case = legacy_start
    entered, release = threading.Event(), threading.Event()
    original = getattr(case.reader, case.reader_name)

    def slow(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return original(*args, **kwargs)

    monkeypatch.setattr(case.reader, case.reader_name, slow)
    reserves = []
    reserved = asyncio.Event()
    baseline = tuple(case.registry.runtime_owners.leases())
    if action == "publish":
        await case.manager._lock.acquire()
    original_reserve = case.registry.runtime_owners.reserve

    def reserve(*args, **kwargs):
        reserves.append(1)
        reserved.set()
        return original_reserve(*args, **kwargs)

    monkeypatch.setattr(case.registry.runtime_owners, "reserve", reserve)
    task = asyncio.create_task(
        case.manager._start_one_unlocked(
            case.key,
            case.manager._workspace_config,
        ),
    )
    try:
        await asyncio.wait_for(asyncio.to_thread(entered.wait, 2), 3)
        assert entered.is_set() and not task.done()
        if action == "cancel":
            task.cancel()
        elif action == "disable":
            case.row.global_enabled = False
        elif action == "unregister":
            case.registry._channels.pop(case.key)
        elif action == "mutate":
            case.manager._workspace_config.channels[case.key][
                "enabled"
            ] = False
        elif action == "replace":
            values = case.manager._workspace_config.channels[case.key]
            case.manager._workspace_config.channels[case.key] = dict(values)
        else:
            release.set()
            await asyncio.wait_for(reserved.wait(), 3)
            await asyncio.sleep(0)
            assert not task.done() and not case.manager.channels
            case.row.global_enabled = False
            case.manager._lock.release()
        release.set()
        expected = (
            pytest.raises(asyncio.CancelledError)
            if action == "cancel"
            else pytest.raises(RuntimeError, match="CHANNEL_PREPARATION_STALE")
        )
        with expected:
            await task
        assert not case.manager.channels
        assert bool(reserves) == (action == "publish")
        assert tuple(case.registry.runtime_owners.leases()) == baseline
    finally:
        if action == "publish" and case.manager._lock.locked():
            case.manager._lock.release()
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["scan", "replace", "cancel"])
async def test_qr_session_rechecks_source_after_scope_read(
    host,
    monkeypatch,
    action,
):
    import threading
    from dataclasses import replace
    from types import SimpleNamespace
    from qwenpaw.app.channels import qrcode_sessions as qr
    from qwenpaw.app.channels.management import (
        ChannelManagementService,
        ManagementError,
    )

    from qwenpaw.plugins.architecture import PluginRecord
    from qwenpaw.plugins.execution_backend import BackendBinding

    source = host.artifact()
    _, manifest = host.loader.read_source_manifest(source)
    binding_description = host.loader._channel_backend.describe(
        source,
        manifest,
    )
    description = binding_description.payload
    record = PluginRecord(
        manifest=manifest,
        source_path=source,
        enabled=True,
        backend_binding=BackendBinding(
            host.loader._channel_backend,
            binding_description,
        ),
    )
    host.loader._loaded_plugins[manifest.id] = record
    row = host.registry.register_channel_descriptor(
        manifest.id,
        description,
        runtime_settings=host.registry.channel_runtime,
    )
    scope = qr.ChannelManagementScope("scan", host.root / "scan", KEY, {})
    management = ChannelManagementService(host.loader)
    sessions = qr.ChannelQRCodeSessions(host.loader, management)
    entered, release = threading.Event(), threading.Event()
    operations = []
    baseline = tuple(host.registry.runtime_owners.leases())

    def read_scope(*args):
        entered.set()
        assert release.wait(3)
        return scope

    async def execute(
        workspace_id,
        channel_key,
        operation,
        parameters,
        **kwargs,
    ):
        operations.append(operation)
        payload = (
            {"scan_url": "https://scan.test", "continuation": "private-scan"}
            if operation == "qrcode.fetch"
            else {"status": "confirmed", "credentials": {"app_id": "fresh"}}
        )
        return SimpleNamespace(
            plugin_id=row.plugin_id,
            workspace_id=workspace_id,
            channel_key=channel_key,
            source_revision=description.source_revision,
            outcome="ok",
            result=payload,
        )

    monkeypatch.setattr(qr, "_read_scope", read_scope)
    monkeypatch.setattr(management, "execute", execute)
    pending = asyncio.create_task(sessions.fetch(scope, {}))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        session = next(iter(sessions._sessions.values()))
        assert host.registry.runtime_owners.resource(session.lease) is session
        assert not operations and not pending.done()
        if action == "replace":
            original = row.runtime_settings
            row.runtime_settings = replace(original)
            assert row.runtime_settings == original
            assert row.runtime_settings is not original
        elif action == "cancel":
            pending.cancel()
            await asyncio.sleep(0)
            assert not pending.done()
            assert session.lease in host.registry.runtime_owners.leases()
        else:
            record.source_path = Path(str(record.source_path))
        release.set()
        if action != "scan":
            expected = (
                pytest.raises(asyncio.CancelledError)
                if action == "cancel"
                else pytest.raises(
                    ManagementError,
                    match="SOURCE_REVISION_MISMATCH",
                )
            )
            with expected:
                await pending
            assert not operations and session.status == "failed"
        else:
            fetched = await pending
            assert fetched.scan_url == "https://scan.test"
            result = await sessions.poll(scope, fetched.poll_token)
            assert result.status == "confirmed" and result.credentials == {
                "app_id": "fresh",
            }
            assert operations == ["qrcode.fetch", "qrcode.poll"]
            await sessions.cancel(scope, fetched.poll_token)
            assert session.status == "cancelled"
        assert not session.continuation and not session.credentials
        assert not session.config and session.timer is None
        assert tuple(host.registry.runtime_owners.leases()) == baseline
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)
        await sessions.aclose()
