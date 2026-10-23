# -*- coding: utf-8 -*-
"""Ordinary desktop plugins use readable support and a writable overlay."""

# pylint: disable=protected-access,redefined-outer-name

from dataclasses import replace
import hashlib
import importlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import sysconfig
from types import SimpleNamespace
import venv
import zipfile

import pytest
from packaging.tags import sys_tags

from qwenpaw.plugins import loader as loader_module
from qwenpaw.plugins.architecture import PluginManifest
from qwenpaw.plugins.channel_adapter import ChannelRuntimeSettings
from qwenpaw.plugins.execution import PluginProcess
from qwenpaw.plugins.execution_backend import BackendBinding

from .test_generic_dependency_gate import wheel

pytestmark = pytest.mark.skipif(
    os.name == "nt",
    reason="Immutable Resources fixture requires POSIX directory permissions",
)


def _contents(root):
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


@pytest.fixture
def desktop(tmp_path, monkeypatch, fresh_registry):
    """Two desktop trees: opaque frozen imports and real readable workers."""
    source = Path(loader_module.__file__).resolve().parents[2]
    resources = tmp_path / "Resources"
    support = resources / "binaries/channel-runtime/site"
    plugins = support / "qwenpaw/plugins"
    shutil.copytree(
        source / "qwenpaw/plugins/execution",
        plugins / "execution",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copy2(
        source / "qwenpaw/plugins/dependency_maintenance.py",
        plugins / "dependency_maintenance.py",
    )
    frozen_loader = (
        resources
        / "binaries/qwenpaw-backend/_internal/qwenpaw/plugins/loader.py"
    )
    frozen_loader.parent.mkdir(parents=True)
    frozen_loader.write_text("# worker support is absent from this tree\n")
    work = tmp_path / "working"
    bucket = (
        f"py{sys.version_info.major}.{sys.version_info.minor}-"
        f"{platform.system().lower()}-{platform.machine().lower()}"
    )
    target = work / "plugin_runtime" / bucket / "site"
    target.mkdir(parents=True)
    settings = ChannelRuntimeSettings(
        python_executable=sys.executable,
        support_root=support,
        qwenpaw_version="test",
        dependency_paths=(support, target),
        dependency_install_target=target,
        runtime_identity={
            "version": list(sys.version_info[:2]),
            "implementation": sys.implementation.name,
            "cache_tag": sys.implementation.cache_tag,
            "sys_platform": sys.platform,
            "system": platform.system(),
            "machine": platform.machine(),
            "supported_tags": [str(tag) for tag in sys_tags()],
        },
    )
    upload = tmp_path / "ordinary-plugin"
    upload.mkdir()
    requirements = upload / "requirements.txt"
    requirements.write_text("frozen-local-sdk==2.0\n")
    index = tmp_path / "wheel-index"
    index.mkdir()
    payload = wheel(index, name="frozen-local-sdk")
    monkeypatch.setattr(loader_module, "_is_frozen", lambda: True)
    monkeypatch.setattr(loader_module, "__file__", str(frozen_loader))
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", work)
    monkeypatch.setenv("QWENPAW_DESKTOP_PY_RUNTIME", sys.executable)
    monkeypatch.setenv("PIP_NO_INDEX", "1")
    monkeypatch.setenv("PIP_FIND_LINKS", str(index))
    monkeypatch.setenv("PIP_NO_CACHE_DIR", "1")
    monkeypatch.setenv("PIP_CONFIG_FILE", os.devnull)
    monkeypatch.delenv("QWENPAW_RUNTIME_PROVISIONER", raising=False)
    monkeypatch.setattr(sys, "path", sys.path.copy())
    audits = []
    audit = PluginProcess.audit

    async def observe(process, spec):
        result = await audit(process, spec)
        audits.append((spec, result.snapshot))
        return result

    monkeypatch.setattr(PluginProcess, "audit", observe)
    # Desktop Resources are not writable. In particular, reader custody must
    # not create mutable lease sidecars beside packaged dependency sites.
    support.parent.chmod(0o555)
    loader = loader_module.PluginLoader(
        [tmp_path / "plugins"],
        channel_runtime=settings,
    )
    yield SimpleNamespace(
        loader=loader,
        settings=settings,
        resources=resources,
        support=support,
        target=target,
        upload=upload,
        requirements=requirements,
        payload=payload,
        audits=audits,
        registry=fresh_registry,
    )
    support.parent.chmod(0o755)
    assert not fresh_registry.runtime_owners.leases("ordinary-plugin")
    sys.modules.pop("frozen_local_sdk", None)
    sys.modules.pop("frozen_common_dependency", None)
    sys.path_importer_cache.pop(str(target), None)
    importlib.invalidate_caches()


@pytest.fixture
def manifest_desktop(desktop, monkeypatch):
    """A launcher manifest with an actual executable inside Resources."""
    from qwenpaw.__version__ import __version__
    from qwenpaw.config import utils as config_utils

    runtime = desktop.resources / "binaries/python-runtime/python"
    executable = runtime / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    # Native venv creation supplies the platform's correct executable layout.
    # Reuse the test environment's offline pip/packaging via a trusted .pth;
    # neither worker auditing nor pip writes bytecode inside Resources.
    venv.EnvBuilder(with_pip=False, symlinks=False).create(runtime)
    local_site = runtime / (
        "Lib/site-packages"
        if os.name == "nt"
        else f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"
    )
    (local_site / "test-runtime.pth").write_text(
        sysconfig.get_path("purelib") + "\n",
    )
    shared_worker = (
        desktop.support / "qwenpaw/channel_protocol/shared_worker.py"
    )
    shared_worker.parent.mkdir(parents=True)
    shared_worker.write_text(
        "# resolver requires the packaged channel worker\n",
    )
    index = desktop.support / "qwenpaw/official_channels/index.json"
    index.parent.mkdir(parents=True)
    index.write_text('{"schema_version":1}\n')
    manifest_path = desktop.resources / "binaries/channel-runtime/runtime.json"
    manifest = {
        "schema_version": 1,
        "host_version": __version__,
        "preset": "light",
        "python_executable": executable.relative_to(
            desktop.resources,
        ).as_posix(),
        "support_root": desktop.support.relative_to(
            desktop.resources,
        ).as_posix(),
        "dependency_paths": [
            desktop.support.relative_to(desktop.resources).as_posix(),
        ],
        "python": desktop.settings.runtime_identity,
        "python_runtime_release": "local-test-runtime",
        "host_wheel_sha256": "0" * 64,
        "official_index_sha256": hashlib.sha256(
            index.read_bytes(),
        ).hexdigest(),
    }
    desktop.support.parent.chmod(0o755)
    manifest_path.write_text(json.dumps(manifest))
    desktop.support.parent.chmod(0o555)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(config_utils, "WORKING_DIR", desktop.target.parents[2])
    monkeypatch.setattr(desktop.registry, "channel_runtime", None)
    monkeypatch.setenv("QWENPAW_TAURI_RESOURCE_DIR", str(desktop.resources))
    monkeypatch.setenv("QWENPAW_CHANNEL_RUNTIME_MANIFEST", str(manifest_path))
    monkeypatch.setenv("QWENPAW_DESKTOP_PY_RUNTIME", str(executable))
    monkeypatch.setenv("QWENPAW_CHANNEL_SUPPORT_ROOT", str(desktop.support))
    monkeypatch.setenv(
        "QWENPAW_CHANNEL_DEPENDENCY_PATHS",
        json.dumps([str(desktop.support)]),
    )
    monkeypatch.setenv("QWENPAW_CHANNEL_PRESET", "light")
    desktop.manifest = manifest
    desktop.manifest_path = manifest_path
    desktop.executable = executable
    local_site.parent.chmod(0o555)
    yield desktop
    local_site.parent.chmod(0o755)


@pytest.mark.asyncio
async def test_frozen_missing_dependency_uses_real_worker_and_host_overlay(
    desktop,
):
    before = _contents(desktop.resources)

    decision = await desktop.loader._ensure_dependencies_installed(
        desktop.upload,
        "ordinary-plugin",
        allow_install=True,
    )

    assert decision.already_satisfied and not decision.missing
    assert not decision.allow_install
    assert len(desktop.audits) >= 2
    assert "frozen-local-sdk" not in desktop.audits[0][1].distributions
    assert (
        desktop.audits[-1][1].distributions["frozen-local-sdk"]["version"]
        == "2.0"
    )
    assert all(
        spec.support_root == desktop.support for spec, _ in desktop.audits
    )
    assert all(
        desktop.support in spec.dependency_paths for spec, _ in desktop.audits
    )
    assert os.environ["QWENPAW_PLUGIN_SITE"] == str(desktop.target)
    assert str(desktop.support) not in sys.path
    installed = desktop.target / "frozen_local_sdk.py"
    assert installed.is_file()
    assert metadata.version("frozen-local-sdk") == "2.0"
    module = importlib.import_module("frozen_local_sdk")
    assert Path(module.__file__) == installed
    assert module.VALUE == "safe-local-addition"
    assert _contents(desktop.resources) == before


@pytest.mark.asyncio
async def test_frozen_packaged_dependency_is_reused_without_acquisition(
    desktop,
    monkeypatch,
):
    host_site = desktop.resources / "binaries/qwenpaw-backend/_internal"
    with zipfile.ZipFile(desktop.payload.path) as archive:
        archive.extractall(desktop.support)
        archive.extractall(host_site)
    monkeypatch.syspath_prepend(str(host_site))
    before = _contents(desktop.resources)

    async def refuse_acquisition(*_args, **_kwargs):
        pytest.fail("A packaged satisfying dependency must not be downloaded")

    monkeypatch.setattr(
        desktop.loader,
        "_acquire_dependency_wheels",
        refuse_acquisition,
    )
    # Explicit preparation must still audit the runtime bundle even when the
    # frozen host already has its own copy of the distribution.
    await desktop.loader._prepare_python_dependencies(
        desktop.requirements,
        "ordinary-plugin",
    )
    decision = await desktop.loader._ensure_dependencies_installed(
        desktop.upload,
        "ordinary-plugin",
        allow_install=True,
    )

    assert decision.already_satisfied and not decision.missing
    assert (
        desktop.audits[-1][1].distributions["frozen-local-sdk"]["version"]
        == "2.0"
    )
    assert not list(desktop.target.iterdir())
    # Frozen imports do not need writable bytecode caches beside packaged code.
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    module = importlib.import_module("frozen_local_sdk")
    assert Path(module.__file__) == host_site / "frozen_local_sdk.py"
    assert str(desktop.support) not in sys.path
    assert _contents(desktop.resources) == before


@pytest.mark.asyncio
async def test_frozen_sdk_install_retains_host_transitive_provider(
    desktop,
    monkeypatch,
):
    host_site = desktop.resources / "binaries/qwenpaw-backend/_internal"
    common = wheel(
        desktop.payload.path.parent,
        name="frozen-common-dependency",
        version="1.0",
    )
    with zipfile.ZipFile(common.path) as archive:
        archive.extractall(host_site)
        archive.extractall(desktop.support)
    wheel(
        desktop.payload.path.parent,
        name="frozen-local-sdk",
        requires=("frozen-common-dependency==1.0",),
    )
    monkeypatch.syspath_prepend(str(host_site))
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    original_provider = importlib.import_module("frozen_common_dependency")
    before = _contents(desktop.resources)

    decision = await desktop.loader._ensure_dependencies_installed(
        desktop.upload,
        "ordinary-plugin",
        allow_install=True,
    )
    assert decision.already_satisfied
    assert "frozen-common-dependency" in desktop.audits[-1][1].distributions
    backend = desktop.loader._python_backend
    description = backend.describe(
        desktop.upload,
        PluginManifest(id="ordinary-plugin", version="1.0"),
    )
    snapshot = await backend.audit_dependencies(description)
    # Duplicate runtime metadata must never make the frozen host's genuine
    # transitive dependency disappear from the evidence used for admission.
    assert "frozen-common-dependency" in snapshot.distributions
    assert (
        Path(
            snapshot.distributions["frozen-common-dependency"][
                "metadata_path"
            ],
        ).parent
        == host_site
    )
    usage = desktop.registry.dependency_usage
    token = usage.declare(description.dependency_declaration(), pending=True)
    try:
        await desktop.loader._admit_dependencies(
            BackendBinding(backend, description),
            token,
            snapshot,
        )
    finally:
        usage.withdraw(token)

    sdk = importlib.import_module("frozen_local_sdk")
    assert Path(sdk.__file__) == desktop.target / "frozen_local_sdk.py"
    assert (
        importlib.import_module("frozen_common_dependency")
        is original_provider
    )
    assert (
        Path(original_provider.__file__)
        == host_site / "frozen_common_dependency.py"
    )
    assert str(desktop.support) not in sys.path
    assert not (desktop.target / "frozen_common_dependency.py").exists()
    assert _contents(desktop.resources) == before


@pytest.mark.asyncio
async def test_frozen_wrong_native_identity_rejects_before_writes(
    desktop,
    monkeypatch,
):
    identity = {
        **desktop.settings.runtime_identity,
        "machine": "wrong-machine",
    }
    monkeypatch.setattr(
        desktop.registry,
        "channel_runtime",
        replace(desktop.settings, runtime_identity=identity),
    )
    before = _contents(desktop.resources)

    with pytest.raises(ValueError, match="CHANNEL_RUNTIME_IDENTITY_MISMATCH"):
        await desktop.loader._prepare_python_dependencies(
            desktop.requirements,
            "ordinary-plugin",
        )

    assert not list(desktop.target.iterdir())
    assert _contents(desktop.resources) == before


@pytest.mark.asyncio
async def test_frozen_missing_readable_worker_rejects_before_writes(desktop):
    from qwenpaw.plugins.execution import ProcessError

    (desktop.support / "qwenpaw/plugins/execution/worker.py").unlink()
    before = _contents(desktop.resources)

    with pytest.raises(ProcessError) as error:
        await desktop.loader._prepare_python_dependencies(
            desktop.requirements,
            "ordinary-plugin",
        )

    assert error.value.reason_code == "BOOTSTRAP_UNAVAILABLE"
    assert not list(desktop.target.iterdir())
    assert _contents(desktop.resources) == before


@pytest.mark.asyncio
async def test_frozen_without_registered_settings_uses_launcher_manifest(
    manifest_desktop,
):
    desktop = manifest_desktop
    before = _contents(desktop.resources)

    decision = await desktop.loader._ensure_dependencies_installed(
        desktop.upload,
        "ordinary-plugin",
        allow_install=True,
    )

    assert decision.already_satisfied and not decision.missing
    assert all(
        Path(spec.python_executable) == desktop.executable
        for spec, _ in desktop.audits
    )
    assert all(
        spec.support_root == desktop.support for spec, _ in desktop.audits
    )
    module = importlib.import_module("frozen_local_sdk")
    assert Path(module.__file__) == desktop.target / "frozen_local_sdk.py"
    assert _contents(desktop.resources) == before


@pytest.mark.asyncio
async def test_frozen_invalid_launcher_manifest_rejects_before_writes(
    manifest_desktop,
):
    desktop = manifest_desktop
    desktop.manifest["support_root"] = "../untrusted-support"
    desktop.manifest_path.write_text(json.dumps(desktop.manifest))
    before = _contents(desktop.resources)

    with pytest.raises(ValueError, match="CHANNEL_RUNTIME_MANIFEST_INVALID"):
        await desktop.loader._prepare_python_dependencies(
            desktop.requirements,
            "ordinary-plugin",
        )

    assert not desktop.audits
    assert not list(desktop.target.iterdir())
    assert _contents(desktop.resources) == before


@pytest.mark.asyncio
async def test_source_dependency_audit_keeps_shared_interpreter_and_support(
    desktop,
    monkeypatch,
):
    from qwenpaw.plugins.execution.environment import shared_dependency_paths

    source_support = Path(__file__).resolve().parents[3] / "src"
    monkeypatch.setattr(loader_module, "_is_frozen", lambda: False)
    monkeypatch.setattr(
        loader_module,
        "__file__",
        str(source_support / "qwenpaw/plugins/loader.py"),
    )
    desktop.requirements.write_text("packaging\n")
    before = _contents(desktop.resources)

    await desktop.loader._prepare_python_dependencies(
        desktop.requirements,
        "ordinary-plugin",
    )

    assert desktop.audits
    assert all(
        spec.python_executable == sys.executable for spec, _ in desktop.audits
    )
    assert all(
        spec.support_root == source_support for spec, _ in desktop.audits
    )
    assert all(
        spec.dependency_paths == shared_dependency_paths()
        for spec, _ in desktop.audits
    )
    assert str(desktop.target) not in sys.path
    assert not list(desktop.target.iterdir())
    assert _contents(desktop.resources) == before
