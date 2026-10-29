# -*- coding: utf-8 -*-
"""Tests for PluginLoader dependency probing and installer security.

Covers the static helpers that decide whether a requirement is already
satisfied (metadata probe + import probe) and enforce installer security.
"""

# pylint: disable=protected-access,redefined-outer-name,unused-argument,use-implicit-booleaness-not-comparison  # noqa: E501
from __future__ import annotations

from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import subprocess

import pytest

from qwenpaw.plugins.loader import PluginLoader

# ---------------------------------------------------------------------------
# _is_requirement_satisfied
# ---------------------------------------------------------------------------


class TestIsRequirementSatisfied:
    def test_installed_package_no_specifier(self):
        from packaging.requirements import Requirement

        # ``packaging`` is a hard dependency, always present.
        req = Requirement("packaging")
        assert PluginLoader._is_requirement_satisfied(req) is True

    def test_installed_package_satisfying_specifier(self):
        from packaging.requirements import Requirement

        req = Requirement("packaging>=1.0")
        assert PluginLoader._is_requirement_satisfied(req) is True

    def test_installed_package_violating_specifier(self):
        from packaging.requirements import Requirement

        # Require an impossibly high version of a real package.
        req = Requirement("packaging>=9999.0")
        assert PluginLoader._is_requirement_satisfied(req) is False

    def test_missing_package_no_specifier(self):
        from packaging.requirements import Requirement

        req = Requirement("this-package-does-not-exist-xyz")
        assert PluginLoader._is_requirement_satisfied(req) is False

    def test_missing_package_with_specifier(self):
        from packaging.requirements import Requirement

        req = Requirement("this-package-does-not-exist-xyz>=1.0")
        assert PluginLoader._is_requirement_satisfied(req) is False

    def test_frozen_bundled_via_import_probe(self):
        """A package present in the env but lacking .dist-info is found.

        The import probe covers frozen desktop builds where dist-info is
        stripped (issue #5209). We simulate by checking a module that is
        importable in this test process.
        """
        from packaging.requirements import Requirement

        # ``json`` is a stdlib module with no dist-info.
        req = Requirement("json")
        assert PluginLoader._is_requirement_satisfied(req) is True


# ---------------------------------------------------------------------------
# _find_unsatisfied_dependencies
# ---------------------------------------------------------------------------


class TestFindUnsatisfiedDependencies:
    def test_missing_requirements_file_returns_empty(self, tmp_path):
        result = PluginLoader._find_unsatisfied_dependencies(
            tmp_path / "requirements.txt",
        )
        assert result == []

    def test_all_satisfied_returns_empty(self, tmp_path):
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("packaging\n", encoding="utf-8")
        result = PluginLoader._find_unsatisfied_dependencies(req_file)
        assert result == []

    def test_missing_package_reported(self, tmp_path):
        req_file = tmp_path / "requirements.txt"
        req_file.write_text(
            "this-package-does-not-exist-xyz>=1.0\n",
            encoding="utf-8",
        )
        result = PluginLoader._find_unsatisfied_dependencies(req_file)
        assert result == ["this-package-does-not-exist-xyz>=1.0"]

    def test_comments_and_blanks_skipped(self, tmp_path):
        req_file = tmp_path / "requirements.txt"
        req_file.write_text(
            "# a comment\n\npackaging\n   \n-r extra.txt\n",
            encoding="utf-8",
        )
        result = PluginLoader._find_unsatisfied_dependencies(req_file)
        assert result == []

    def test_option_lines_skipped(self, tmp_path):
        req_file = tmp_path / "requirements.txt"
        req_file.write_text(
            "--index-url https://example.com\npackaging\n",
            encoding="utf-8",
        )
        result = PluginLoader._find_unsatisfied_dependencies(req_file)
        assert result == []

    def test_malformed_line_skipped_not_raised(self, tmp_path):
        req_file = tmp_path / "requirements.txt"
        req_file.write_text(
            "not a valid requirement !!!\npackaging\n",
            encoding="utf-8",
        )
        result = PluginLoader._find_unsatisfied_dependencies(req_file)
        assert result == []

    def test_mixed_satisfied_and_missing(self, tmp_path):
        req_file = tmp_path / "requirements.txt"
        req_file.write_text(
            "packaging\nthis-missing-one-abc\n",
            encoding="utf-8",
        )
        result = PluginLoader._find_unsatisfied_dependencies(req_file)
        assert result == ["this-missing-one-abc"]


@pytest.mark.parametrize(
    ("tool", "version", "safe"),
    [
        ("pip", "26.2.1", False),
        ("pip", "26.2.2", True),
        ("uv", "0.13.3", False),
        ("uv", "0.13.4", True),
    ],
)
def test_dependency_installer_security_versions(
    monkeypatch,
    tool,
    version,
    safe,
):
    from qwenpaw.utils import runtime_environment

    calls = []

    def version_probe(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            f"{tool} {version}\n",
            "",
        )

    monkeypatch.setattr(runtime_environment.subprocess, "run", version_probe)
    if tool == "pip":
        check = partial(
            runtime_environment.require_pip,
            "chosen-python",
            isolated=True,
        )
        expected = ["chosen-python", "-I", "-B", "-m", "pip", "--version"]
    else:
        check = partial(runtime_environment.require_uv, "chosen-uv")
        expected = ["chosen-uv", "--version"]
    if safe:
        check()
    else:
        with pytest.raises(RuntimeError):
            check()
    assert calls == [expected]


@pytest.mark.asyncio
async def test_old_installer_cannot_acquire_dependency_wheels(
    tmp_path,
    monkeypatch,
):
    """The controlled wheel path must reject before resolver execution."""
    loader = PluginLoader([tmp_path])
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("sample-sdk==1\n", encoding="utf-8")
    resolver = Mock()
    guard = Mock(side_effect=RuntimeError("Unsafe pip 26.2.1"))
    monkeypatch.setattr(loader, "_run_subprocess_with_streaming_log", resolver)
    monkeypatch.setattr("qwenpaw.plugins.loader.require_pip", guard)

    with pytest.raises(RuntimeError, match="Unsafe pip"):
        await loader._acquire_dependency_wheels(
            SimpleNamespace(),
            SimpleNamespace(python_executable="chosen-python"),
            SimpleNamespace(distributions={}, marker_environment={}),
            tmp_path / "site",
            "sample-plugin",
            requirements,
        )
    guard.assert_called_once_with("chosen-python", isolated=True)
    resolver.assert_not_called()
    assert requirements.read_text(encoding="utf-8") == "sample-sdk==1\n"


@pytest.mark.asyncio
async def test_controlled_wheels_use_certifi_floor_without_editing_source(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.utils.runtime_environment import CERTIFI_REQUIREMENT

    loader = PluginLoader([tmp_path])
    requirements = tmp_path / "requirements.txt"
    source_text = "--no-index\nsample-sdk==1\n"
    requirements.write_text(source_text, encoding="utf-8")
    events = []

    def safe_installer(python, *, isolated):
        assert python == "chosen-python" and isolated is True
        events.append("checked")
        return True

    def inspect_resolution(command, **_kwargs):
        events.append("wheel")
        assert events == ["checked", "wheel"]
        assert command[:6] == [
            "chosen-python",
            "-I",
            "-B",
            "-m",
            "pip",
            "wheel",
        ]
        assert "install" not in command
        effective = Path(command[command.index("-r") + 1])
        assert effective != requirements
        assert effective.read_text(encoding="utf-8").splitlines() == [
            "--no-index",
            "sample-sdk==1",
            "",
            CERTIFI_REQUIREMENT,
        ]
        assert requirements.read_text(encoding="utf-8") == source_text
        return subprocess.CompletedProcess(command, 0, "", "")

    async def inspect_gate(_process, _spec, **options):
        events.append("gate")
        assert options["requirements_file"] != requirements
        assert (
            CERTIFI_REQUIREMENT
            in options["requirements_file"]
            .read_text(
                encoding="utf-8",
            )
            .splitlines()
        )
        assert options["expected_snapshot"].distributions == {}
        assert options["wheels"] == ()

    monkeypatch.setattr("qwenpaw.plugins.loader.require_pip", safe_installer)
    monkeypatch.setattr(
        loader,
        "_run_subprocess_with_streaming_log",
        inspect_resolution,
    )
    monkeypatch.setattr(
        "qwenpaw.plugins.dependency_gate.prepare_shared_dependencies",
        inspect_gate,
    )
    await loader._acquire_dependency_wheels(
        SimpleNamespace(),
        SimpleNamespace(python_executable="chosen-python", code_root=tmp_path),
        SimpleNamespace(distributions={}, marker_environment={}),
        tmp_path / "site",
        "sample-plugin",
        requirements,
    )
    assert events == ["checked", "wheel", "gate"]
    assert requirements.read_text(encoding="utf-8") == source_text


@pytest.mark.asyncio
async def test_certifi_floor_refuses_old_immutable_provider_before_download(
    tmp_path,
    monkeypatch,
):
    loader = PluginLoader([tmp_path])
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("sample-sdk==1\n", encoding="utf-8")
    certifi = {"version": "2026.7.22", "requires_dist": ()}
    refuse = Mock(
        side_effect=RuntimeError("protected certifi needs desktop update"),
    )
    context = SimpleNamespace(
        immutable_providers=lambda: {"certifi": certifi},
        refuse_immutable_provider=refuse,
    )
    resolver, guard = Mock(), Mock()
    monkeypatch.setattr(loader, "_run_subprocess_with_streaming_log", resolver)
    monkeypatch.setattr("qwenpaw.plugins.loader.require_pip", guard)

    with pytest.raises(RuntimeError, match="protected certifi"):
        await loader._acquire_dependency_wheels(
            SimpleNamespace(),
            SimpleNamespace(python_executable="chosen-python"),
            SimpleNamespace(
                distributions={"certifi": certifi},
                marker_environment={},
            ),
            tmp_path / "site",
            "sample-plugin",
            requirements,
            dependency_context=context,
        )
    refuse.assert_called_once_with("certifi", certifi)
    guard.assert_not_called()
    resolver.assert_not_called()
    assert requirements.read_text(encoding="utf-8") == "sample-sdk==1\n"


@pytest.mark.asyncio
async def test_immutable_installer_without_pip_never_runs_ensurepip(
    tmp_path,
    monkeypatch,
):
    loader = PluginLoader([tmp_path])
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("sample-sdk==1\n", encoding="utf-8")
    resolver = Mock()
    guard = Mock(return_value=False)
    context = SimpleNamespace(
        immutable_providers=lambda: {},
        runtime_identity={"protocol": 1},
    )
    monkeypatch.setattr(loader, "_run_subprocess_with_streaming_log", resolver)
    monkeypatch.setattr("qwenpaw.plugins.loader.require_pip", guard)

    with pytest.raises(RuntimeError, match="bundled pip is missing"):
        await loader._acquire_dependency_wheels(
            SimpleNamespace(),
            SimpleNamespace(python_executable="chosen-python"),
            SimpleNamespace(distributions={}, marker_environment={}),
            tmp_path / "site",
            "sample-plugin",
            requirements,
            dependency_context=context,
        )
    guard.assert_called_once_with("chosen-python", isolated=True)
    resolver.assert_not_called()


@pytest.mark.asyncio
async def test_mutable_missing_pip_is_rechecked_and_reaudited_after_bootstrap(
    tmp_path,
    monkeypatch,
):
    loader = PluginLoader([tmp_path])
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("sample-sdk==1\n", encoding="utf-8")
    original = SimpleNamespace(distributions={}, marker_environment={})
    refreshed = SimpleNamespace(
        distributions={"pip": {"version": "26.2.2"}},
        marker_environment={},
    )
    events = []

    def check(python, *, isolated):
        assert python == "chosen-python" and isolated is True
        events.append("check")
        return events.count("check") > 1

    def run(command, **_kwargs):
        if command[-1] == "ensurepip":
            events.append("bootstrap")
            assert command == ["chosen-python", "-I", "-m", "ensurepip"]
        else:
            events.append("wheel")
            assert "wheel" in command and "install" not in command
            assert (
                Path(command[command.index("--constraint") + 1]).read_text(
                    encoding="utf-8",
                )
                == "pip==26.2.2\n"
            )
        return subprocess.CompletedProcess(command, 0, "", "")

    async def audit(_spec):
        events.append("audit")
        return SimpleNamespace(snapshot=refreshed)

    async def gate(_process, _spec, **options):
        events.append("gate")
        assert options["expected_snapshot"] is refreshed

    monkeypatch.setattr("qwenpaw.plugins.loader.require_pip", check)
    monkeypatch.setattr(loader, "_run_subprocess_with_streaming_log", run)
    monkeypatch.setattr(
        "qwenpaw.plugins.dependency_gate.prepare_shared_dependencies",
        gate,
    )
    await loader._acquire_dependency_wheels(
        SimpleNamespace(audit=audit),
        SimpleNamespace(python_executable="chosen-python", code_root=tmp_path),
        original,
        tmp_path / "site",
        "sample-plugin",
        requirements,
    )
    assert events == ["check", "bootstrap", "audit", "check", "wheel", "gate"]
    assert requirements.read_text(encoding="utf-8") == "sample-sdk==1\n"


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["ready", "changed", "cancel"])
async def test_async_loader_leases_before_loop_registry_publication(
    tmp_path,
    monkeypatch,
    action,
):
    import asyncio
    import threading
    from qwenpaw.plugins import dependency_maintenance, loader as loader_mod

    loop_thread = threading.get_ident()
    events = []
    started, release = threading.Event(), threading.Event()
    runtime = SimpleNamespace(
        python_executable="chosen-python",
        support_root=tmp_path,
        dependency_paths=(tmp_path / "site",),
        dependency_install_target=tmp_path / "site",
        runtime_identity={"protocol": 1},
    )
    original_registry = loader_mod.PluginRegistry

    def lease(paths):
        assert threading.get_ident() != loop_thread
        assert paths == runtime.dependency_paths
        events.append("lease")
        started.set()
        assert release.wait(3)

    class Registry(original_registry):
        _instance = None

        def __init__(self):
            assert threading.get_ident() == loop_thread
            assert events == ["lease"]
            events.append("registry")
            super().__init__()

        def configure_channel_runtime(self, settings):
            assert threading.get_ident() == loop_thread
            assert settings is runtime
            events.append("publish")

    monkeypatch.setattr(dependency_maintenance, "lease_environment", lease)
    monkeypatch.setattr(loader_mod, "PluginRegistry", Registry)
    creation = asyncio.create_task(
        loader_mod.PluginLoader.create([tmp_path], channel_runtime=runtime),
    )
    try:
        assert await asyncio.to_thread(started.wait, 2)
        assert events == ["lease"]
        assert not creation.done()
        if action == "changed":
            runtime.runtime_identity["protocol"] = 2
        elif action == "cancel":
            creation.cancel()
            await asyncio.sleep(0)
            assert not creation.done()
    finally:
        release.set()
    if action != "ready":
        expected = (
            pytest.raises(asyncio.CancelledError)
            if action == "cancel"
            else pytest.raises(RuntimeError, match="IDENTITY_CHANGED")
        )
        with expected:
            await asyncio.wait_for(creation, 5)
        assert events == ["lease"]
        return
    result = await asyncio.wait_for(creation, 5)
    assert isinstance(result.registry, Registry)
    assert events == ["lease", "registry", "publish"]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["stable", "changed", "preflight_invalid"])
async def test_preparation_and_admission_keep_only_required_real_audits(
    tmp_path,
    monkeypatch,
    case,
):
    import sys
    from qwenpaw.plugins.dependency_gate import GateDecision
    from qwenpaw.plugins.dependency_usage import (
        DependencyDeclaration,
        DependencyUsageRegistry,
    )
    from qwenpaw.plugins.execution_backend import BackendBinding
    from qwenpaw.plugins.lifecycle import PluginLifecycle
    from qwenpaw.plugins.ownership import RuntimeOwners
    from qwenpaw.plugins.python_backend import PythonBackend

    site, added, source = (
        tmp_path / part for part in ("site", "added", "plugin")
    )
    for path in (site, added, source):
        path.mkdir()
    for root, name in ((site, "initial"), (added, "added")):
        info = root / f"{name}-1.0.dist-info"
        info.mkdir()
        (info / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n",
        )
        (info / "RECORD").write_text(f"{info.name}/METADATA,,\n")
    dormant = tmp_path / "not-yet-visible"
    added.rename(dormant)
    monkeypatch.setattr(sys, "path", [str(site), str(added)])

    async def ensure(*args, **kwargs):
        return GateDecision(False, True)

    backend = PythonBackend(SimpleNamespace(ensure_dependencies=ensure))
    description = SimpleNamespace(
        manifest=SimpleNamespace(id="audit-count", sdk=None),
        source_path=source,
        payload=None,
        requirements=(),
    )
    binding = BackendBinding(backend, description)
    usage = DependencyUsageRegistry(RuntimeOwners())
    loader = SimpleNamespace(registry=SimpleNamespace(dependency_usage=usage))
    lifecycle = PluginLifecycle(loader)
    real_audit, audits = backend.audit_dependencies, []
    calls = []

    async def counted(*args, **kwargs):
        if case == "changed" and not calls:
            # Keep the captured search path identity stable while a previously
            # absent root becomes visible after lock hints were selected.
            dormant.rename(added)
        calls.append(True)
        observed = await real_audit(*args, **kwargs)
        audits.append(observed)
        return observed

    monkeypatch.setattr(backend, "audit_dependencies", counted)
    if case == "preflight_invalid":
        from qwenpaw.plugins.dependency_maintenance import repair_marker

        marker = repair_marker(site)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("repair required")
        with pytest.raises(RuntimeError, match="DEPENDENCY_REPAIR_REQUIRED"):
            await lifecycle.preflight_backend(
                binding,
                allow_install=False,
                probe=False,
                owns_dependency_env=False,
            )
        assert len(calls) == 1
        return
    prepared = await lifecycle.prepare_backend(
        binding,
        allow_install=False,
        probe=False,
    )
    assert calls == []
    token = usage.declare(DependencyDeclaration("audit-count", None, (), None))
    admitted = await PluginLoader._admit_dependencies(
        loader,
        binding,
        token,
        prepared,
    )
    assert len(calls) == (2 if case == "changed" else 1)
    # A newly visible root rejects the stale lock scope before scanning;
    # only the retry can produce the complete admitted evidence.
    assert audits == [admitted]
    assert set(admitted.distributions) == (
        {"initial", "added"} if case == "changed" else {"initial"}
    )


@pytest.fixture
def controlled_import_snapshot(monkeypatch):
    """Exercise real module changes without scanning other suites' imports."""
    from qwenpaw.plugins import dependency_transaction as transaction

    snapshot = transaction._module_snapshot
    names = {
        "_qwenpaw_stale_dependency_test",
        "_qwenpaw_other_import",
        "_qwenpaw_added_import",
        "_qwenpaw_supplemental_import",
    }
    monkeypatch.setattr(
        transaction,
        "_module_snapshot",
        lambda: tuple(entry for entry in snapshot() if entry[0] in names),
    )


def test_host_dependency_record_retains_loaded_ownership(tmp_path):
    import os
    import sys
    from importlib.metadata import PathDistribution
    from pathlib import PurePosixPath
    from qwenpaw.plugins.python_backend import _files_for_loaded_origins

    info = tmp_path / "sample-1.0.dist-info"
    info.mkdir()
    source = tmp_path / "shared_ns" / "loaded.py"
    source.parent.mkdir()
    source.write_text("VALUE = 1")
    record = info / "RECORD"
    record.write_text(
        "shared_ns/./loaded.py,,9\n"
        "unrelated.py,,12\n"
        "shared_ns/missing.py,,1\n",
    )
    paths = ["shared_ns/loaded.py", "shared_ns/missing.py"]
    origins = {os.path.normcase(os.path.normpath(path)) for path in paths}
    distribution = PathDistribution(info)
    expected = paths[:1] if sys.version_info >= (3, 12) else paths
    assert _files_for_loaded_origins(distribution, origins) == [
        PurePosixPath(path) for path in expected
    ]
    from qwenpaw.plugins.python_backend import _observe_host_dependencies

    (info / "METADATA").write_text("Name: sample\nVersion: 1.0\n")
    loaded = (("shared_ns.loaded", str(source)),)
    original = record.read_text()
    _, imported = _observe_host_dependencies(
        tmp_path / "plugin",
        (tmp_path,),
        loaded,
    )
    assert "sample" in imported
    record.write_text("unrelated.py,,12\n")
    _, imported = _observe_host_dependencies(
        tmp_path / "plugin",
        (tmp_path,),
        loaded,
    )
    assert "sample" not in imported
    record.write_text(original)
    _, imported = _observe_host_dependencies(
        tmp_path / "plugin",
        (tmp_path,),
        loaded,
    )
    assert "sample" in imported
    with record.open("a") as stream:
        stream.write("unrelated.py,,not-a-size\n")
    with pytest.raises(ValueError):
        _files_for_loaded_origins(distribution, origins)


@pytest.mark.parametrize(
    "layout",
    [
        "owned",
        "unowned",
        "independent",
        "alias",
        "namespace",
        "namespace_overlap",
        "namespace_parent",
        "namespace_module",
        "mixed",
        "missing_cache",
        "unowned_cache",
        "cache_without_source",
        "non_cache_file",
    ],
)
def test_dependency_directory_classification_retains_provider_ownership(
    tmp_path,
    layout,
):
    from qwenpaw.plugins.execution.dependencies import (
        _installed_metadata,
        dependency_sites,
        observe_dependencies,
    )
    from qwenpaw.plugins.python_backend import _observe_host_dependencies

    site = tmp_path / "site"
    nested = site / "owner" / "_vendor"
    nested.mkdir(parents=True)

    def install(root, name, version, files):
        info = root / f"{name}-{version}.dist-info"
        info.mkdir()
        (info / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
        )
        entries = [f"{info.name}/METADATA", f"{info.name}/RECORD", *files]
        (info / "RECORD").write_text("".join(f"{p},,\n" for p in entries))
        return info

    namespace = layout.startswith("namespace")
    loaded_module = "shared_namespace.one" if namespace else "sample_sdk"
    module = {
        "namespace": "shared_namespace/two.py",
        "namespace_overlap": "shared_namespace/one.py",
        "namespace_parent": "shared_namespace/__init__.py",
        "namespace_module": "shared_namespace.py",
    }.get(layout, "sample_sdk.py")
    public = site / module
    public.parent.mkdir(exist_ok=True)
    public.write_text("VALUE = 'public'\n")
    embedded = nested / (
        "shared_namespace/one.py" if namespace else "sample_sdk.py"
    )
    embedded.parent.mkdir(exist_ok=True)
    embedded.write_text("VALUE = 'embedded'\n")
    public_info = install(site, "sample_sdk", "2.0", [module])
    nested_info = install(
        nested,
        "sample_sdk",
        "1.0",
        [embedded.relative_to(nested).as_posix()],
    )
    owned = (
        []
        if layout == "unowned"
        else [
            path.relative_to(site).as_posix()
            for path in (
                embedded,
                nested_info / "METADATA",
                nested_info / "RECORD",
            )
        ]
    )
    owner_info = install(site, "owner", "1.0", owned)
    if layout in {
        "missing_cache",
        "unowned_cache",
        "cache_without_source",
        "non_cache_file",
    }:
        cache = nested / "__pycache__/sample_sdk.cpython-312.pyc"
        extra = (
            cache.with_suffix(".txt") if layout == "non_cache_file" else cache
        )
        with (nested_info / "RECORD").open("a") as stream:
            stream.write(f"{extra.relative_to(nested).as_posix()},,\n")
        if layout == "unowned_cache":
            cache.parent.mkdir()
            cache.write_bytes(b"unowned")
        elif layout == "cache_without_source":
            record = nested_info / "RECORD"
            record.write_text(
                record.read_text().replace("sample_sdk.py,,\n", ""),
            )
    if layout == "mixed":
        neighbor = nested / "independent.py"
        neighbor.write_text("VALUE = 'independent'\n")
        neighbor_info = install(
            nested,
            "independent",
            "1.0",
            [neighbor.name],
        )
    if layout == "independent":
        other = tmp_path / "independent"
        other.mkdir()
        install(other, "sample_sdk", "3.0", [])
        paths = (site, nested, other)
    elif layout == "alias":
        alias = tmp_path / "site-alias"
        alias.symlink_to(site, target_is_directory=True)
        paths = (site, alias, alias / "owner/_vendor")
    else:
        paths = (site, nested)
    classified = dependency_sites(paths)
    # Lock hints stay conservative until the RECORD audit proves ownership.
    assert classified[:2] == (str(site.resolve()), str(nested.resolve()))
    packet = {"code_root": tmp_path / "plugin", "_audit_sites": paths}
    snapshot = observe_dependencies(packet)
    if layout not in {
        "unowned",
        "independent",
        "unowned_cache",
        "cache_without_source",
        "non_cache_file",
    }:
        expected_sites = (
            (str(site.resolve()), str(nested.resolve()))
            if layout == "mixed"
            else (str(site.resolve()),)
        )
        assert snapshot.dependency_sites == expected_sites
        assert snapshot.distributions["sample-sdk"]["metadata_path"] == (
            str(public_info)
        )
        if layout == "mixed":
            assert snapshot.distributions["independent"]["metadata_path"] == (
                str(neighbor_info)
            )
    else:
        assert "sample-sdk" not in snapshot.distributions
        assert _installed_metadata(classified)[1]["sample-sdk"] == (
            "DEPENDENCY_ENVIRONMENT_AMBIGUOUS"
        )
        return
    observed, imported = _observe_host_dependencies(
        tmp_path / "plugin",
        paths,
        ((loaded_module, str(embedded)),),
    )
    assert observed.distributions["sample-sdk"]["metadata_path"] == (
        str(public_info)
    )
    assert imported["owner"]["metadata_path"] == str(owner_info)
    assert ("sample-sdk" in imported) is (layout != "namespace")
    from dataclasses import replace
    from qwenpaw.plugins.dependency_gate import evaluate_shared_dependencies

    use = SimpleNamespace(
        plugin_id="loaded-owner",
        instance_id=None,
        generation=None,
        origin="host",
        active=True,
        environment=observed,
        snapshot=replace(observed, distributions=imported),
    )
    decision = evaluate_shared_dependencies(
        None,
        observed,
        plugin_id="incoming",
        uses=(use,),
    )
    assert not decision.require_restart
    assert not decision.host_conflicts
    if layout == "namespace":
        return

    # Observe a real loaded embedded copy before the public provider exists.
    import shutil

    public.unlink()
    shutil.rmtree(public_info)
    before, imported = _observe_host_dependencies(
        tmp_path / "plugin",
        paths,
        ((loaded_module, str(embedded)),),
    )
    other_use = None
    if layout == "namespace_overlap":
        other_embedded = nested / "shared_namespace/two.py"
        other_embedded.write_text("VALUE = 'other embedded'\n")
        with (owner_info / "RECORD").open("a") as stream:
            stream.write(f"{other_embedded.relative_to(site).as_posix()},,\n")
        other_before, other_imported = _observe_host_dependencies(
            tmp_path / "plugin",
            paths,
            (("shared_namespace.two", str(other_embedded)),),
        )
        assert imported["owner"]["loaded_modules"] == ("shared_namespace.one",)
        assert other_imported["owner"]["loaded_modules"] == (
            "shared_namespace.two",
        )
        other_use = SimpleNamespace(
            **{
                **vars(use),
                "plugin_id": "loaded-other",
                "snapshot": replace(
                    other_before,
                    distributions=other_imported,
                ),
            },
        )
    public.write_text("VALUE = 'public'\n")
    install(site, "sample_sdk", "2.0", [module])
    use.snapshot = replace(before, distributions=imported)
    decision = evaluate_shared_dependencies(
        None,
        observed,
        plugin_id="incoming",
        uses=(use,),
    )
    assert decision.require_restart
    assert any(
        "sample-sdk shadows a loaded embedded module" in conflict
        for conflict in decision.host_conflicts
    )
    if other_use is not None:
        for consumers in ((other_use, use), (use, other_use)):
            decision = evaluate_shared_dependencies(
                None,
                observed,
                plugin_id="incoming",
                uses=consumers,
            )
            assert decision.require_restart
            assert decision.host_conflicts == [
                "host loaded-owner: sample-sdk shadows a loaded "
                "embedded module",
            ]
        # The next gate must reread the same provider's changed RECORD.
        (public_info / "RECORD").write_text("shared_namespace/two.py,,\n")
        decision = evaluate_shared_dependencies(
            None,
            observed,
            plugin_id="incoming",
            uses=(use, other_use),
        )
        assert decision.require_restart
        assert decision.host_conflicts == [
            "host loaded-other: sample-sdk shadows a loaded "
            "embedded module",
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change,expected",
    [
        ("stable", "imported"),
        ("missing", "empty"),
        ("no_file", "imported"),
        ("empty_no_file", "empty"),
        ("unrelated_addition", "imported"),
        ("unrelated_removal", "imported"),
        ("unrelated_identity", "imported"),
        ("unrelated_origin", "imported"),
        ("order", "imported"),
        ("identity", "stale"),
        ("origin", "stale"),
        ("origin_into", "stale"),
        ("removal", "stale"),
        ("addition", "stale"),
    ],
)
async def test_dependency_import_resolution_rejects_changed_module(
    tmp_path,
    monkeypatch,
    controlled_import_snapshot,
    change,
    expected,
):
    import asyncio
    import sys
    import threading
    from types import ModuleType
    from qwenpaw.plugins import dependency_transaction as transaction
    from qwenpaw.utils import io_utils

    name, unrelated = "_qwenpaw_stale_dependency_test", "_qwenpaw_other_import"
    source, other = tmp_path / "sdk.py", tmp_path / "other.py"
    if change != "missing":
        source.touch()
    other.touch()
    module, outside = ModuleType(name), ModuleType(unrelated)
    module.__file__ = str(other if change == "origin_into" else source)
    outside.__file__ = str(other)
    if change != "addition":
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setitem(sys.modules, unrelated, outside)
    started, release = threading.Event(), threading.Event()
    offload, canonical = io_utils.run_sync_io, transaction.canonical
    loop_thread = threading.get_ident()

    def resolve(path):
        assert threading.get_ident() != loop_thread
        return canonical(path)

    async def paused(operation, *args, **kwargs):
        def worker():
            result = operation(*args, **kwargs)
            started.set()
            assert release.wait(3)
            return result

        return await offload(worker)

    monkeypatch.setattr(transaction, "canonical", resolve)
    monkeypatch.setattr(io_utils, "run_sync_io", paused)
    probe = asyncio.create_task(
        transaction.imported_changes_async(
            {"old": {} if change == "empty_no_file" else {str(source): {}}},
        ),
    )
    try:
        assert await asyncio.to_thread(started.wait, 2)
        if change == "order":
            sys.modules[name] = sys.modules.pop(name)
        elif change in {"no_file", "empty_no_file", "unrelated_addition"}:
            added = ModuleType("_qwenpaw_added_import")
            if change == "unrelated_addition":
                added.__file__ = str(other)
            monkeypatch.setitem(sys.modules, added.__name__, added)
        elif change in {"removal", "unrelated_removal"}:
            del sys.modules[name if change == "removal" else unrelated]
        elif change in {"identity", "addition", "unrelated_identity"}:
            replacement = ModuleType(
                unrelated if change == "unrelated_identity" else name,
            )
            replacement.__file__ = str(
                other if change == "unrelated_identity" else source,
            )
            monkeypatch.setitem(sys.modules, replacement.__name__, replacement)
        elif change == "origin":
            module.__file__ = str(other)
        elif change == "origin_into":
            module.__file__ = str(source)
        elif change == "unrelated_origin":
            outside.__file__ = str(tmp_path / "missing.py")
    finally:
        release.set()
        await asyncio.wait_for(
            asyncio.gather(probe, return_exceptions=True),
            5,
        )
    if expected == "stale":
        with pytest.raises(RuntimeError, match="DEPENDENCY_PLAN_STALE"):
            await asyncio.wait_for(probe, 5)
    else:
        assert await asyncio.wait_for(probe, 5) == (
            [name] if expected == "imported" else []
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["unrelated", "relevant", "continuous"])
async def test_dependency_import_resolution_checks_supplemental_changes(
    tmp_path,
    monkeypatch,
    controlled_import_snapshot,
    change,
):
    import asyncio
    import sys
    import threading
    from types import ModuleType
    from qwenpaw.plugins import dependency_transaction as transaction
    from qwenpaw.utils import io_utils

    source = tmp_path / "sdk.py"
    source.touch()
    others = [tmp_path / f"other_{index}.py" for index in range(8)]
    for other in others:
        other.touch()
    loop = asyncio.get_running_loop()
    offload = io_utils.run_sync_io
    passes = 0

    def change_module(release):
        if passes <= 2 or change == "continuous":
            module = ModuleType("_qwenpaw_supplemental_import")
            module.__file__ = str(
                source
                if change == "relevant" and passes == 2
                else others[passes - 1],
            )
            monkeypatch.setitem(sys.modules, module.__name__, module)
        release.set()

    async def paused(operation, *args, **kwargs):
        def worker():
            nonlocal passes
            result = operation(*args, **kwargs)
            passes += 1
            assert passes <= 8, "import validation retried without a bound"
            release = threading.Event()
            loop.call_soon_threadsafe(change_module, release)
            assert release.wait(3)
            return result

        return await offload(worker)

    monkeypatch.setattr(io_utils, "run_sync_io", paused)
    probe = transaction.imported_changes_async({"old": {str(source): {}}})
    if change == "unrelated":
        assert await asyncio.wait_for(probe, 5) == []
    else:
        with pytest.raises(RuntimeError, match="DEPENDENCY_PLAN_STALE"):
            await asyncio.wait_for(probe, 5)
    assert passes >= 2


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["python", "channel"])
async def test_async_dependency_targets_reject_changed_host_paths(
    tmp_path,
    monkeypatch,
    kind,
):
    import sys
    from qwenpaw.plugins.python_backend import PythonBackend

    from qwenpaw.plugins.channel_adapter import (
        ChannelBackend,
        ChannelRuntimeSettings,
    )

    runtime = ChannelRuntimeSettings(
        python_executable=sys.executable,
        support_root=tmp_path,
        qwenpaw_version="test",
        selected_channels=None,
        dependency_paths=(tmp_path / "site",),
    )
    selection = SimpleNamespace(runtime=runtime)
    backend = (
        PythonBackend(SimpleNamespace())
        if kind == "python"
        else ChannelBackend(
            SimpleNamespace(runtime_settings=lambda: selection.runtime),
        )
    )
    admission = await backend.prepare_dependency_targets(
        SimpleNamespace(id="test", source_path=tmp_path / "plugin"),
    )
    admission.validate()
    if kind == "python":
        monkeypatch.setattr(
            sys,
            "path",
            [*sys.path, str(tmp_path / "new-site")],
        )
    else:
        assert admission.targets == (tmp_path / "site",)
        selection.runtime = None
    with pytest.raises(RuntimeError, match="IDENTITY_CHANGED"):
        admission.validate()


@pytest.mark.asyncio
@pytest.mark.parametrize("stale", [False, True])
async def test_frozen_dependency_path_preparation_and_loop_publication(
    tmp_path,
    monkeypatch,
    stale,
):
    import asyncio
    import os
    import sys
    import threading
    from qwenpaw.plugins import loader as loader_mod

    root = tmp_path / "runtime"
    bucket = root / "python"
    target = bucket / "bundle-new" / "site"
    old = bucket / "bundle-old" / "site"
    paths = [str(old), str(bucket / "site"), str(tmp_path / "host")]
    monkeypatch.setattr(sys, "path", paths[:])
    monkeypatch.setenv("QWENPAW_PLUGIN_SITE", "before")
    monkeypatch.setattr(loader_mod, "_is_frozen", lambda: True)
    monkeypatch.setattr(loader_mod, "_plugin_runtime_dir", lambda: root)
    loader = loader_mod.PluginLoader([tmp_path])
    loop_thread = threading.get_ident()
    started, release = threading.Event(), threading.Event()
    prepare = loader_mod._prepare_plugin_site_path
    publish = loader_mod._publish_plugin_site_path
    publications = []

    def resolve(site, snapshot):
        assert threading.get_ident() != loop_thread
        assert tuple(snapshot) == tuple(paths)
        result = prepare(site, snapshot)
        assert sys.path == paths
        assert os.environ["QWENPAW_PLUGIN_SITE"] == "before"
        started.set()
        assert release.wait(3)
        return result

    def commit(prepared):
        assert threading.get_ident() == loop_thread
        publications.append(prepared)
        publish(prepared)

    monkeypatch.setattr(loader_mod, "_prepare_plugin_site_path", resolve)
    monkeypatch.setattr(loader_mod, "_publish_plugin_site_path", commit)
    pending = asyncio.create_task(
        loader._publish_dependency_site(target),
    )
    try:
        assert await asyncio.to_thread(started.wait, 2)
        if stale:
            sys.path.append(str(tmp_path / "concurrent-site"))
    finally:
        release.set()
    if stale:
        with pytest.raises(RuntimeError, match="IDENTITY_CHANGED"):
            await asyncio.wait_for(pending, 5)
        assert not publications
        assert os.environ["QWENPAW_PLUGIN_SITE"] == "before"
    else:
        await asyncio.wait_for(pending, 5)
        assert len(publications) == 1
        assert sys.path == [str(target), str(tmp_path / "host")]
        assert os.environ["QWENPAW_PLUGIN_SITE"] == str(target)


@pytest.mark.asyncio
@pytest.mark.parametrize("leave_marker", [False, True])
async def test_load_waits_for_dependency_writer(
    tmp_path,
    monkeypatch,
    fresh_registry,
    bounded_dependency_environment,
    leave_marker,
):
    """Classify a publication marker only after its real writer exits."""
    import asyncio
    import json
    import os
    import sys
    from contextlib import suppress

    from .timing import WAIT_TIMEOUT

    from qwenpaw.plugins import dependency_maintenance as maintenance
    from qwenpaw.plugins import install_lock

    site = bounded_dependency_environment
    monkeypatch.syspath_prepend(str(site))
    monkeypatch.setenv("QWENPAW_WORKING_DIR", str(tmp_path / "work"))
    source = tmp_path / "plugins" / "publication-probe"
    source.mkdir(parents=True)
    (source / "plugin.json").write_text(
        json.dumps(
            {
                "id": "publication-probe",
                "version": "1.0.0",
                "type": "tool",
                "entry": {"backend": "main.py"},
            },
        ),
    )
    (source / "main.py").write_text(
        "class Plugin:\n"
        "    def register(self, api):\n"
        "        pass\n"
        "plugin = Plugin()\n",
    )
    writer_code = """
import importlib.util
import sys
from pathlib import Path
spec = importlib.util.spec_from_file_location('maintenance', sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
site = Path(sys.argv[2])
with m.file_lock(m._gate(site)), m.file_lock(m._admission_gate(site)):
    marker = m.repair_marker(site)
    marker.write_text('Shared dependency publication requires verification.\\n')
    print('READY', flush=True)
    assert sys.stdin.readline().strip() == 'RELEASE'
    if sys.argv[3] == 'False':
        marker.unlink()
print('COMPLETED', flush=True)
"""
    writer = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        writer_code,
        maintenance.__file__,
        str(site),
        str(leave_marker),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    loading = None
    try:
        assert (
            await asyncio.wait_for(
                writer.stdout.readline(),
                WAIT_TIMEOUT,
            )
            == b"READY\n"
        )
        gates = {
            (stat.st_dev, stat.st_ino)
            for stat in (
                maintenance._gate(site).stat(),
                maintenance._admission_gate(site).stat(),
            )
        }
        contended = asyncio.Event()
        loop = asyncio.get_running_loop()

        def observe_lock(real_lock):
            def acquire(fd):
                acquired = real_lock(fd)
                stat = os.fstat(fd)
                if (stat.st_dev, stat.st_ino) in gates and not acquired:
                    loop.call_soon_threadsafe(contended.set)
                return acquired

            return acquire

        monkeypatch.setattr(
            install_lock,
            "_acquire_os_lock",
            observe_lock(install_lock._acquire_os_lock),
        )
        monkeypatch.setattr(
            maintenance,
            "_try_lock",
            observe_lock(maintenance._try_lock),
        )
        loader = PluginLoader([source.parent])
        loading = asyncio.create_task(
            loader.load_all_plugins(
                {"publication-probe": {"enabled": True}},
                activate=True,
            ),
        )
        await asyncio.wait_for(contended.wait(), WAIT_TIMEOUT)
        assert not loading.done()
        writer.stdin.write(b"RELEASE\n")
        await writer.stdin.drain()
        output, error = await asyncio.wait_for(
            writer.communicate(),
            WAIT_TIMEOUT,
        )
        assert writer.returncode == 0, error
        assert output == b"COMPLETED\n"
        records = await asyncio.wait_for(loading, WAIT_TIMEOUT)
    finally:
        if writer.returncode is None:
            writer.kill()
            await writer.communicate()
        if loading is not None and not loading.done():
            loading.cancel()
            with suppress(asyncio.CancelledError):
                await asyncio.wait_for(loading, WAIT_TIMEOUT)
    record = records["publication-probe"]
    if leave_marker:
        assert record.status == "failed", record.diagnostics
        assert "DEPENDENCY_REPAIR_REQUIRED" in str(record.diagnostics)
        assert record.instance is None
        assert not loader.registry.leftover_registrations("publication-probe")
    else:
        assert record.status == "active", record.diagnostics
        await loader.unload_plugin("publication-probe")
        # Reuse the same host registry: a transient marker must not retain an
        # unknown host consumer that blocks every subsequent admission.
        following = PluginLoader([source.parent])
        records = await following.load_all_plugins(
            {"publication-probe": {"enabled": True}},
            activate=True,
        )
        record = records["publication-probe"]
        assert record.status == "active", record.diagnostics
        await following.unload_plugin("publication-probe")
