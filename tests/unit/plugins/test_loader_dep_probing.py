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
from qwenpaw.plugins.execution.dependencies import canonical_environment_path

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
        DependencyUsageRegistry,
    )
    from qwenpaw.plugins.execution_backend import (
        BackendBinding,
        PluginDescription,
    )
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
    description = PluginDescription(
        SimpleNamespace(id="audit-count", sdk=None),
        source,
        None,
        None,
        source_identity="source",
        requirements=(),
    )
    binding = BackendBinding(backend, description)
    usage = DependencyUsageRegistry(RuntimeOwners())
    loader = PluginLoader.__new__(PluginLoader)
    loader.registry = SimpleNamespace(dependency_usage=usage)
    lifecycle = PluginLifecycle(loader)
    real_audit, audits = backend.audit_dependencies, []
    real_targets = backend.prepare_dependency_targets

    async def counted(*args, **kwargs):
        observed = await real_audit(*args, **kwargs)
        audits.append(observed)
        return observed

    async def targets(*args, **kwargs):
        prepared = await real_targets(*args, **kwargs)
        if case == "changed":
            dormant.rename(added)
            sys.path.append(str(tmp_path / "new-search-root"))
        return prepared

    monkeypatch.setattr(backend, "audit_dependencies", counted)
    monkeypatch.setattr(backend, "prepare_dependency_targets", targets)
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
        assert audits == []
        return
    prepared = await lifecycle.prepare_backend(
        binding,
        allow_install=False,
        probe=False,
    )
    assert audits == []
    token = usage.declare(description.dependency_declaration())
    if case == "changed":
        with pytest.raises(
            RuntimeError,
            match="DEPENDENCY_ENVIRONMENT_IDENTITY_CHANGED",
        ):
            await PluginLoader._admit_dependencies(
                loader,
                binding,
                token,
                prepared,
            )
        assert usage.snapshot().uses[0].environment is None
    else:
        assert (
            await PluginLoader._admit_dependencies(
                loader,
                binding,
                token,
                prepared,
            )
            is None
        )
        use = usage.snapshot().uses[0]
        assert str(canonical_environment_path(site)) in use.environment.sites
        assert use.snapshot is None
    assert audits == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "empty",
        "satisfied",
        "missing",
        "missing_package",
        "transitive",
        "repair",
        "stale",
        "duplicate",
        "bad_record",
        "fresh_metadata",
        "fresh_record",
        "child_record",
    ],
)
async def test_existing_dependency_read_admission_keeps_safety_boundaries(
    tmp_path,
    monkeypatch,
    case,
):
    import sys
    from qwenpaw.plugins.dependency_gate import SharedDependencyError
    from qwenpaw.plugins.dependency_usage import (
        DependencyUsageRegistry,
    )
    from qwenpaw.plugins.ownership import RuntimeKey, RuntimeOwners
    from qwenpaw.plugins.execution_backend import PluginDescription
    from qwenpaw.plugins.python_backend import PythonBackend

    site, source = tmp_path / "site", tmp_path / "plugin"
    site.mkdir()
    source.mkdir()
    info = site / "sample-1.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text("Name: sample\nVersion: 1.0\n")
    (info / "RECORD").write_text("sample.py,,\n")
    (site / "sample.py").write_text("VALUE = 1\n")
    if case == "transitive":
        (info / "METADATA").write_text(
            "Name: sample\nVersion: 1.0\nRequires-Dist: child>=2\n",
        )
    if case == "duplicate":
        duplicate = site / "sample-1.1.dist-info"
        duplicate.mkdir()
        (duplicate / "METADATA").write_text("Name: sample\nVersion: 1.1\n")
        (duplicate / "RECORD").write_text("other_sample.py,,\n")
        (site / "other_sample.py").write_text("VALUE = 2\n")
    if case == "bad_record":
        (info / "RECORD").write_text("sample.py,,not-a-size\n")
    monkeypatch.setattr(sys, "path", [str(site)])
    requirements = (
        ("sample>=2",)
        if case == "missing"
        else (
            ("sample>=1",) if case not in {"empty", "repair", "stale"} else ()
        )
    )
    if case == "missing_package":
        requirements = ("absent>=1",)
    description = PluginDescription(
        SimpleNamespace(id="read-consumer", sdk=None),
        source,
        None,
        None,
        source_identity="source",
        requirements=requirements,
    )
    owners = RuntimeOwners()
    usage = DependencyUsageRegistry(owners)
    declaration = description.dependency_declaration()
    token = usage.declare(declaration)
    replacement = None
    if case == "stale":
        usage.withdraw(token)
        replacement = usage.declare(declaration)
    if case == "repair":
        from qwenpaw.plugins.dependency_maintenance import repair_marker

        marker = repair_marker(site)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("repair required")
    backend = PythonBackend(SimpleNamespace())
    audited = []
    real_audit = backend.audit_dependencies

    async def audit(*args, **kwargs):
        audited.append(True)
        return await real_audit(*args, **kwargs)

    monkeypatch.setattr(backend, "audit_dependencies", audit)
    before = {
        p.relative_to(site): p.read_bytes()
        for p in site.rglob("*")
        if p.is_file()
    }
    if case in {"fresh_metadata", "fresh_record", "child_record"}:
        import asyncio
        import os
        from qwenpaw.plugins.install_lock import environment_observation

        async with environment_observation((site,)):
            assert (
                await backend.admit_existing(
                    description,
                    usage=usage,
                    token=token,
                )
                is None
            )
            changed = info / (
                "METADATA" if case == "fresh_metadata" else "RECORD"
            )
            stamp = changed.stat()
            changed.write_text(
                "Name: sample\nVersion: 0.5\n"
                if case == "fresh_metadata"
                else "sample.py,,not-a-size\n",
            )
            os.utime(changed, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
            fresh_token = usage.declare(declaration)
            pending = (
                asyncio.create_task(
                    backend.admit_existing(
                        description,
                        usage=usage,
                        token=fresh_token,
                    ),
                )
                if case == "child_record"
                else None
            )
        with pytest.raises(SharedDependencyError) as rejected:
            if pending is not None:
                await pending
            else:
                await backend.admit_existing(
                    description,
                    usage=usage,
                    token=fresh_token,
                )
        expected = (
            {"DEPENDENCY_UNSATISFIED"}
            if case == "fresh_metadata"
            else {"DEPENDENCY_METADATA_INVALID", "DEPENDENCY_PLAN_UNVERIFIED"}
        )
        assert rejected.value.decision.reason_code in expected
        assert usage.snapshot().uses[-1].environment is None
        return
    if case in {
        "missing",
        "missing_package",
        "transitive",
        "repair",
        "stale",
        "duplicate",
        "bad_record",
    }:
        if case == "stale":
            with pytest.raises(
                ValueError,
                match="DEPENDENCY_DECLARATION_MISMATCH",
            ):
                await backend.admit_existing(
                    description,
                    usage=usage,
                    token=token,
                )
        else:
            with pytest.raises(SharedDependencyError) as rejected:
                await backend.admit_existing(
                    description,
                    usage=usage,
                    token=token,
                )
            assert (
                rejected.value.decision.reason_code
                in {
                    "missing": {"DEPENDENCY_UNSATISFIED"},
                    "missing_package": {"DEPENDENCY_UNSATISFIED"},
                    "transitive": {"DEPENDENCY_UNSATISFIED"},
                    "repair": {"DEPENDENCY_REPAIR_REQUIRED"},
                    "duplicate": {"DEPENDENCY_ENVIRONMENT_AMBIGUOUS"},
                    "bad_record": {
                        "DEPENDENCY_METADATA_INVALID",
                        "DEPENDENCY_PLAN_UNVERIFIED",
                    },
                }[case]
            )
            if case in {"missing", "missing_package", "transitive"}:
                failed_requirement = {
                    "missing": "sample>=2",
                    "missing_package": "absent>=1",
                    "transitive": "child>=2",
                }[case]
                assert str(rejected.value).startswith(
                    "DEPENDENCY_UNSATISFIED: read-consumer: "
                    f"{failed_requirement}",
                )
                assert rejected.value.decision.missing == [failed_requirement]
        if replacement is not None:
            assert usage.has_declaration(replacement)
        assert all(
            use.snapshot is None and use.environment is None
            for use in usage.snapshot().uses
        )
    else:
        assert (
            await backend.admit_existing(description, usage=usage, token=token)
            is None
        )
        uses = usage.snapshot().uses
        assert len(uses) == 1
        assert uses[0].environment is not None
        assert (
            str(canonical_environment_path(site)) in uses[0].environment.sites
        )
        assert uses[0].snapshot is None
        assert audited == []
        lease = owners.reserve(
            "read-consumer",
            RuntimeKey("plugin", "read-consumer", "test"),
            source,
            instance_id="first",
        )
        usage.bind(lease, token)
        runtime = next(
            use for use in usage.snapshot().uses if use.origin == "runtime"
        )
        assert runtime.active and runtime.environment == uses[0].environment
        assert runtime.snapshot is None
        assert usage.capture_admissions((lease,))[lease] is token
    assert audited == []
    assert {
        p.relative_to(site): p.read_bytes()
        for p in site.rglob("*")
        if p.is_file()
    } == before


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


def test_dependency_sites_classify_batch_once(tmp_path, monkeypatch):
    from collections import Counter
    from pathlib import PureWindowsPath
    from qwenpaw.plugins.execution import dependencies as deps

    standard = tmp_path / "stdlib"
    package = standard / "site-packages"
    roots = [package / "sdk", standard / "encodings", tmp_path / "overlay"]
    for path in roots:
        path.mkdir(parents=True)
    monkeypatch.setattr(
        deps.sysconfig,
        "get_path",
        lambda name: str(
            package if name in {"purelib", "platlib"} else standard,
        ),
    )
    monkeypatch.setattr(deps.sysconfig, "get_config_var", lambda name: None)
    canonical, calls = deps.canonical_environment_path, Counter()

    def counted(path):
        calls[str(path)] += 1
        return canonical(path)

    monkeypatch.setattr(deps, "canonical_environment_path", counted)
    assert deps.dependency_sites(roots * 3, explicit=roots) == (
        str(canonical(roots[0])),
        str(canonical(roots[2])),
    )
    assert calls[str(standard)] == calls[str(package)] == 1
    assert all(calls[str(path)] == 1 for path in roots)
    assert deps.protected_dependency_target(roots[1])
    assert not deps.protected_dependency_target(roots[0])
    monkeypatch.setattr(deps, "Path", PureWindowsPath)
    package = PureWindowsPath("C:/Python/Lib/site-packages")
    protection = ({str(package)}, {str(package.parent)}, set())
    assert not deps._protected_dependency_target(package / "sdk", protection)
    assert deps._protected_dependency_target(
        PureWindowsPath("C:/Python/Lib/SITE-PACKAGES/sdk"),
        protection,
    )

    class WindowsDirectory(PureWindowsPath):
        def is_dir(self):
            return True

        def resolve(self):
            return self

    monkeypatch.setattr(deps, "Path", WindowsDirectory)
    monkeypatch.setattr(deps, "canonical_environment_path", WindowsDirectory)
    distinct = [
        WindowsDirectory(f"C:/external/{name}") for name in ("sdk", "SDK")
    ]
    assert deps.dependency_sites(distinct) == tuple(map(str, distinct))


def test_host_delta_skips_own_source_inventory(tmp_path, monkeypatch):
    import json
    from collections import Counter
    from pathlib import PureWindowsPath
    from qwenpaw.plugins.execution import dependencies as deps
    from qwenpaw.plugins import python_backend as backend

    site, source = tmp_path / "site", tmp_path / "plugin"
    site.mkdir()
    source.mkdir()
    external = site / "sdk.py"
    external.write_text("VALUE = 1\n")
    own = source / "main.py"
    own.write_text("VALUE = 2\n")
    info = site / "sdk-1.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text("Name: sdk\nVersion: 1.0\n")
    (info / "RECORD").write_text("sdk.py,,\n")
    expected_metadata = str(deps.canonical_environment_path(info))
    baseline, imported = backend._observe_host_dependencies(
        source,
        (site,),
        (("sdk", str(external)),),
    )
    assert imported["sdk"]["version"] == "1.0"
    read_inventory, calls = deps.read_dependency_inventory, []
    resolve, resolved = Path.resolve, Counter()

    def counted_resolve(path, *args, **kwargs):
        resolved[path] += 1
        return resolve(path, *args, **kwargs)

    def counted(*args, **kwargs):
        calls.append(args)
        return read_inventory(*args, **kwargs)

    monkeypatch.setattr(deps, "read_dependency_inventory", counted)
    monkeypatch.setattr(Path, "resolve", counted_resolve)
    observed, imported = backend._observe_host_delta(
        source,
        (site,),
        (("main", str(own)),),
        baseline,
    )
    assert observed.sites == baseline.sites
    assert imported == {}
    assert calls == []
    assert resolved[own] == 1
    observe, full_calls = backend._observe_host_dependencies, []

    def counted_observe(*args, **kwargs):
        if kwargs.get("_snapshot") is None:
            full_calls.append(args)
        return observe(*args, **kwargs)

    monkeypatch.setattr(backend, "_observe_host_dependencies", counted_observe)
    shadow = tmp_path / "external" / "json.py"
    shadow.parent.mkdir()
    shadow.write_text("VALUE = 3\n")
    # A standard-library name alone cannot establish trusted provenance.
    _, imported = backend._observe_host_delta(
        source,
        (site,),
        (("json", str(shadow)),),
        baseline,
    )
    assert imported == {}
    assert len(full_calls) == 1
    full_calls.clear()
    unowned = site / "sdk" / "unowned.py"
    unowned.parent.mkdir()
    unowned.write_text("VALUE = 4\n")
    _, imported = backend._observe_host_delta(
        source,
        (site,),
        (("sdk", str(external)), ("sdk.unowned", str(unowned))),
        baseline,
    )
    assert imported["sdk"]["metadata_path"] == expected_metadata
    assert len(full_calls) == 1
    full_calls.clear()
    _, imported = backend._observe_host_delta(
        source,
        (site,),
        (("json", json.__file__),),
        baseline,
    )
    assert imported == {}
    assert full_calls == []
    calls.clear()
    alias = source / "linked.py"
    try:
        alias.symlink_to(external)
    except OSError:
        pytest.skip("symlinks unavailable")
    _, imported = backend._observe_host_delta(
        source,
        (site,),
        (("sdk", str(alias)),),
        baseline,
    )
    assert imported["sdk"]["metadata_path"] == expected_metadata
    assert len(calls) == 1
    assert resolved[alias] == 1
    windows_resolved = Counter()

    class WindowsOrigin(PureWindowsPath):
        def resolve(self):
            windows_resolved[str(self)] += 1
            return own if self.name == "sdk.py" else external

    monkeypatch.setattr(
        backend,
        "Path",
        lambda path: WindowsOrigin(path)
        if str(path).replace("\\", "/") in {"C:/sdk.py", "C:/SDK.py"}
        else Path(path),
    )
    _, imported = backend._observe_host_delta(
        source,
        (site,),
        (("main", "C:/sdk.py"), ("sdk", "C:/SDK.py")),
        baseline,
    )
    assert imported["sdk"]["metadata_path"] == expected_metadata
    assert windows_resolved == {"C:\\sdk.py": 1, "C:\\SDK.py": 1}
    with monkeypatch.context() as patch:
        patch.setattr(backend, "Path", PureWindowsPath)
        patch.setattr(
            deps,
            "_dependency_protection_roots",
            lambda: (
                {"c:/Python/Lib/site-packages"},
                {"c:/Python/Lib"},
                set(),
            ),
        )
        for directory, expected in (("lib", set()), ("Lib", {"json"})):
            origin = str(
                PureWindowsPath(f"C:/Python/{directory}/json/__init__.py"),
            )
            assert (
                backend._stdlib_modules(
                    (("json", origin),),
                    {origin: PureWindowsPath(origin)},
                )
                == expected
            )


@pytest.mark.asyncio
async def test_host_observation_reuses_only_scoped_raw_inputs(
    tmp_path,
    monkeypatch,
):
    import asyncio
    import os
    from collections import Counter
    from email.parser import Parser
    from importlib.metadata import PathDistribution
    from qwenpaw.plugins.execution import dependencies as deps
    from qwenpaw.plugins import python_backend as backend
    from qwenpaw.plugins.install_lock import (
        environment_observation,
        observation_inputs,
        observation_write,
    )

    site, source = tmp_path / "site", tmp_path / "plugin"
    info = site / "sdk-1.0.dist-info"
    info.mkdir(parents=True)
    module = site / "shared_ns" / "actual.py"
    module.parent.mkdir()
    module.write_text("VALUE = 1\n")
    metadata, record = info / "METADATA", info / "RECORD"
    headers = (
        "Name: sdk\r\nVersion: 1.0\r\nRequires-Python: >=3.11\r\n"
        "Requires-Dist: child>=1;\r\n    extra == 'optional'\r\n"
    )
    metadata.write_bytes(
        (headers + "\r\n" + "Long description.\r\n" * 4096).encode("utf-8"),
    )
    record_text = "shared_ns/actual.py,,\n"
    record.write_text(record_text)
    expected_metadata = str(deps.canonical_environment_path(info))
    loaded = (("shared_ns.actual", str(module)),)
    read_text, reader = PathDistribution.read_text, deps.csv.reader
    expected = PathDistribution(info).metadata
    parse, parsed = Parser.parsestr, []
    reads, parses = Counter(), []

    def counted_headers(parser, text, *args, **kwargs):
        if text and text.startswith("Name: sdk"):
            parsed.append(text)
        return parse(parser, text, *args, **kwargs)

    def counted_read(distribution, filename):
        if Path(distribution._path) == info:
            reads[filename] += 1
        return read_text(distribution, filename)

    def counted_parse(lines, *args, **kwargs):
        lines = tuple(lines)
        if lines == tuple(record_text.splitlines()):
            parses.append(lines)
        return reader(lines, *args, **kwargs)

    monkeypatch.setattr(PathDistribution, "read_text", counted_read)
    monkeypatch.setattr(deps.csv, "reader", counted_parse)
    monkeypatch.setattr(Parser, "parsestr", counted_headers)
    async with environment_observation((site,)):
        inputs = observation_inputs()
        async with environment_observation((site,)):
            assert observation_inputs() is inputs

        async def inherited_inputs():
            return observation_inputs()

        assert await asyncio.create_task(inherited_inputs()) is None
        baseline, first = backend._observe_host_dependencies(
            source,
            (site,),
            loaded,
            inventory=inputs,
        )
        assert first["sdk"]["metadata_path"] == expected_metadata
        assert first["sdk"]["requires_dist"] == tuple(
            expected.get_all("Requires-Dist"),
        )
        assert parsed and all(
            "Long description." not in text for text in parsed
        )
        first["sdk"]["version"] = "mutated consumer row"
        # Its module top-level differs from the distribution name, forcing
        # delta's conservative full fallback to share the same raw inputs.
        _, imported = backend._observe_host_delta(
            tmp_path / "other-plugin",
            (site,),
            loaded,
            baseline,
            inventory=inputs,
        )
        assert imported["sdk"]["version"] == "1.0"
        assert reads["METADATA"] == reads["RECORD"] == 1
        assert len(parses) == 1
        excluded, imported = backend._observe_host_dependencies(
            site,
            (site,),
            loaded,
            inventory=inputs,
        )
        assert excluded.distributions == imported == {}
        metadata_stat, record_stat = metadata.stat(), record.stat()
        with observation_write():
            metadata.write_text("Name: sdk\nVersion: 2.0\n")
            record.write_text("unrelated.py,,\n")
            for path, stat in (
                (metadata, metadata_stat),
                (record, record_stat),
            ):
                os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        current, imported = backend._observe_host_dependencies(
            source,
            (site,),
            loaded,
            inventory=inputs,
        )
        assert current.distributions["sdk"]["version"] == "2.0"
        assert imported == {}
        assert reads["METADATA"] == reads["RECORD"] == 2
    assert observation_inputs() is None
    metadata.write_text("Name: sdk\nVersion: 3.0\n")
    record.write_text(record_text)
    for path, stat in ((metadata, metadata_stat), (record, record_stat)):
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    async with environment_observation((site,)):
        assert observation_inputs() is not inputs
        _, imported = backend._observe_host_dependencies(
            source,
            (site,),
            loaded,
            inventory=observation_inputs(),
        )
        assert imported["sdk"]["version"] == "3.0"
        assert reads["METADATA"] == reads["RECORD"] == 3


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
    record_stat = record.stat()
    _, imported = _observe_host_dependencies(
        tmp_path / "plugin",
        (tmp_path,),
        loaded,
    )
    assert "sample" in imported
    record.write_text("unrelated.py,,12\n")
    os.utime(record, ns=(record_stat.st_atime_ns, record_stat.st_mtime_ns))
    _, imported = _observe_host_dependencies(
        tmp_path / "plugin",
        (tmp_path,),
        loaded,
    )
    assert "sample" not in imported
    record.write_text(original)
    os.utime(record, ns=(record_stat.st_atime_ns, record_stat.st_mtime_ns))
    _, imported = _observe_host_dependencies(
        tmp_path / "plugin",
        (tmp_path,),
        loaded,
    )
    assert "sample" in imported
    # Admission generations retain independent historical pins, even when
    # later observations no longer contain the module or show a new version.
    from dataclasses import replace
    from qwenpaw.plugins.dependency_usage import (
        DependencyDeclaration,
        DependencyUsageRegistry,
    )
    from qwenpaw.plugins.ownership import RuntimeOwners

    usage = DependencyUsageRegistry(RuntimeOwners())
    declaration = DependencyDeclaration("history", "old", (), None)
    old_token = usage.declare(declaration)
    candidate = usage.declare(
        replace(declaration, source_revision="candidate"),
    )
    snapshot, imported = _observe_host_dependencies(
        tmp_path / "plugin",
        (tmp_path,),
        loaded,
    )
    snapshot = replace(snapshot, distributions=imported)
    usage.observe_host(old_token, snapshot)
    metadata = info / "METADATA"
    metadata_stat = metadata.stat()
    metadata.write_text("Name: sample\nVersion: 2.0\n")
    os.utime(
        metadata,
        ns=(metadata_stat.st_atime_ns, metadata_stat.st_mtime_ns),
    )
    current, current_imported = _observe_host_dependencies(
        tmp_path / "plugin",
        (tmp_path,),
        loaded,
    )
    assert current_imported["sample"]["version"] == "2.0"
    usage.observe_host(
        candidate,
        replace(current, distributions=current_imported),
    )
    usage.observe_host(old_token, replace(current, distributions={}))
    usage.withdraw(old_token)
    historical = {
        use.source_revision: use
        for use in usage.snapshot().uses
        if use.origin == "host"
    }
    assert (
        historical["old"].snapshot.distributions["sample"]["version"] == "1.0"
    )
    assert (
        historical["candidate"].snapshot.distributions["sample"]["version"]
        == "2.0"
    )
    assert usage.has_declaration(candidate)
    metadata.write_text("Name: sample\nVersion: 1.0\n")
    with record.open("a") as stream:
        stream.write("unrelated.py,,not-a-size\n")
    with pytest.raises(ValueError):
        _files_for_loaded_origins(distribution, origins)


@pytest.mark.asyncio
@pytest.mark.parametrize("layout", ["ordinary", "namespace_alias", "unknown"])
async def test_host_dependency_boundaries_keep_preexisting_and_removed_imports(
    tmp_path,
    monkeypatch,
    layout,
):
    import sys
    from types import ModuleType
    from qwenpaw.plugins.dependency_usage import (
        DependencyDeclaration,
        DependencyUsageRegistry,
    )
    from qwenpaw.plugins.ownership import RuntimeOwners
    from qwenpaw.plugins.python_backend import PythonBackend

    site = tmp_path / "site"
    site.mkdir()
    future = tmp_path / "future-site"
    monkeypatch.setattr(sys, "path", [str(site), str(future)])
    description = SimpleNamespace(
        manifest=SimpleNamespace(id="host-history"),
        source_path=tmp_path / "plugin",
    )
    usage = DependencyUsageRegistry(RuntimeOwners())
    token = usage.declare(
        DependencyDeclaration("host-history", "source", (), None),
    )
    names = [
        "_qwenpaw_before_register",
        "_qwenpaw_in_register",
        "_qwenpaw_in_teardown",
    ]
    rows = (
        [(name, f"{name}.py") for name in names]
        if layout == "ordinary"
        else [
            ("real-owner", "shared_ns/actual.py"),
            ("shared-ns", "shared_ns/other.py"),
            ("plainowner", "plainowner.py"),
        ]
    )
    for owner, relative in rows:
        info = site / f"{owner}-1.0.dist-info"
        info.mkdir()
        (info / "METADATA").write_text(f"Name: {owner}\nVersion: 1.0\n")
        (info / "RECORD").write_text(f"{relative},,\n")
        path = site / relative
        path.parent.mkdir(exist_ok=True)
        path.write_text("VALUE = 1\n")
    if layout != "ordinary":
        await PythonBackend.observe_host_dependencies(
            description,
            usage,
            token,
        )
        if layout == "unknown":
            (site / "real-owner-1.0.dist-info/RECORD").write_text(
                "shared_ns/actual.py,,not-a-size\n",
            )
    events = (
        [(name,) for name in names]
        if layout == "ordinary"
        else [("plainowner", "shared_ns.actual")]
    )
    for added in events:
        for name in added:
            module = ModuleType(name)
            module.__file__ = str(site / (name.replace(".", "/") + ".py"))
            monkeypatch.setitem(sys.modules, name, module)
        await PythonBackend.observe_host_dependencies(
            description,
            usage,
            token,
        )
        if layout != "ordinary" or added == (names[1],):
            for name in names[:2] if layout == "ordinary" else added:
                monkeypatch.delitem(sys.modules, name)
            await PythonBackend.observe_host_dependencies(
                description,
                usage,
                token,
            )
    if layout == "ordinary":
        own = description.source_path / "main.py"
        own.parent.mkdir()
        own.touch()
        module = ModuleType("_qwenpaw_own_source")
        module.__file__ = str(own)
        monkeypatch.setitem(sys.modules, module.__name__, module)
        await PythonBackend.observe_host_dependencies(
            description,
            usage,
            token,
        )
    usage.withdraw(token)
    histories = [use for use in usage.snapshot().uses if use.origin == "host"]
    assert len(histories) == 1
    host = histories[0]
    if layout == "unknown":
        assert host.environment is None and host.snapshot is None
    else:
        expected = (
            {name.replace("_", "-") for name in names}
            if layout == "ordinary"
            else {"real-owner", "plainowner"}
        )
        assert set(host.snapshot.distributions) == expected
        assert all(
            row["version"] == "1.0"
            for row in host.snapshot.distributions.values()
        )

    async def observe_source(source, revision, admission=None):
        incoming = SimpleNamespace(
            manifest=description.manifest,
            source_path=source,
        )
        admission = admission or usage.declare(
            DependencyDeclaration("host-history", revision, (), None),
        )
        await PythonBackend.observe_host_dependencies(
            incoming,
            usage,
            admission,
        )
        return admission, [
            use
            for use in usage.snapshot().uses
            if use.origin == "host" and use.source_revision == revision
        ]

    if layout == "ordinary":
        import os
        from qwenpaw.plugins import python_backend as backend

        monkeypatch.delitem(sys.modules, "_qwenpaw_own_source")
        state = backend._host_dependency_state

        def owned_state():
            paths, loaded = state()
            return paths, tuple(row for row in loaded if row[0] in names)

        monkeypatch.setattr(backend, "_host_dependency_state", owned_state)
        observe, full_calls = backend._observe_host_dependencies, []

        def counted_observe(*args, **kwargs):
            if kwargs.get("_snapshot") is None:
                full_calls.append(args)
            return observe(*args, **kwargs)

        monkeypatch.setattr(
            backend,
            "_observe_host_dependencies",
            counted_observe,
        )
        other_token, other_hosts = await observe_source(
            tmp_path / "other-plugin",
            "other-source",
        )
        other_host = other_hosts[0]
        remaining = names[-1].replace("_", "-")
        assert set(other_host.snapshot.distributions) == {remaining}
        assert other_host.snapshot.distributions[remaining]["version"] == "1.0"
        assert full_calls == []
        future.mkdir()
        _, other_hosts = await observe_source(
            tmp_path / "other-plugin",
            "other-source",
            other_token,
        )
        other_host = other_hosts[0]
        assert other_host.snapshot is not None
        assert other_host.environment is not None
        assert other_host.snapshot.distributions[remaining]["version"] == "1.0"
        from qwenpaw.plugins.execution.dependencies import (
            canonical_environment_path,
        )

        assert (
            str(canonical_environment_path(future))
            in other_host.snapshot.sites
        )
        future.rmdir()
        _, other_hosts = await observe_source(
            tmp_path / "other-plugin",
            "other-source",
            other_token,
        )
        assert other_hosts[0].environment is not None
        assert (
            other_hosts[0].snapshot.distributions[remaining]["version"]
            == "1.0"
        )
        assert (
            str(canonical_environment_path(future))
            in other_hosts[0].snapshot.sites
        )
        # The same module object moving to another file must establish fresh
        # ownership; neither module count nor an existing row proves its owner.
        metadata = site / f"{names[0]}-1.0.dist-info" / "METADATA"
        stamp = metadata.stat()
        metadata.write_text(f"Name: {names[0]}\nVersion: 2.0\n")
        os.utime(metadata, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        sys.modules[names[-1]].__file__ = str(site / f"{names[0]}.py")
        _, other_hosts = await observe_source(
            tmp_path / "other-plugin",
            "other-source",
            other_token,
        )
        other_host = other_hosts[0]
        assert set(other_host.snapshot.distributions) == {
            remaining,
            names[0].replace("_", "-"),
        }
        assert other_host.snapshot.distributions[remaining]["version"] == "1.0"
        assert (
            other_host.snapshot.distributions[names[0].replace("_", "-")][
                "version"
            ]
            == "2.0"
        )
        assert set(host.snapshot.distributions) == expected
        assert all(
            row["version"] == "1.0"
            for row in host.snapshot.distributions.values()
        )
        _, excluded_hosts = await observe_source(site, "excluded-source")
        assert excluded_hosts == []
    elif layout == "namespace_alias":
        from qwenpaw.plugins import python_backend as backend

        unclaimed = site / "unclaimed.py"
        unclaimed.write_text("VALUE = 1\n")
        module = ModuleType("unclaimed")
        module.__file__ = str(unclaimed)
        monkeypatch.setitem(sys.modules, module.__name__, module)
        state = backend._host_dependency_state

        def unclaimed_state():
            paths, loaded = state()
            return paths, tuple(row for row in loaded if row[0] == "unclaimed")

        monkeypatch.setattr(backend, "_host_dependency_state", unclaimed_state)
        for revision in ("unclaimed-before", "unclaimed-after"):
            if revision == "unclaimed-after":
                info = site / "claimed-1.0.dist-info"
                info.mkdir()
                (info / "METADATA").write_text("Name: claimed\nVersion: 1.0\n")
                (info / "RECORD").write_text("unclaimed.py,,\n")
            _, histories = await observe_source(tmp_path / revision, revision)
            if revision == "unclaimed-before":
                assert histories == []
            else:
                assert set(histories[0].snapshot.distributions) == {"claimed"}
                assert (
                    histories[0].snapshot.distributions["claimed"]["version"]
                    == "1.0"
                )


@pytest.mark.asyncio
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
async def test_dependency_directory_classification_retains_provider_ownership(
    tmp_path,
    layout,
    monkeypatch,
):
    from qwenpaw.plugins.execution.dependencies import (
        _installed_metadata,
        canonical_environment_path,
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
    site_key, nested_key = (
        str(canonical_environment_path(root)) for root in (site, nested)
    )
    # Lock hints stay conservative until the RECORD audit proves ownership.
    assert classified[:2] == (site_key, nested_key)
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
            (site_key, nested_key) if layout == "mixed" else (site_key,)
        )
        assert snapshot.dependency_sites == expected_sites
        assert snapshot.distributions["sample-sdk"]["metadata_path"] == (
            str(canonical_environment_path(public_info))
        )
        if layout == "mixed":
            assert snapshot.distributions["independent"]["metadata_path"] == (
                str(canonical_environment_path(neighbor_info))
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
        str(canonical_environment_path(public_info))
    )
    assert imported["owner"]["metadata_path"] == str(
        canonical_environment_path(owner_info),
    )
    assert ("sample-sdk" in imported) is (layout != "namespace")
    if layout in {"owned", "namespace"}:
        import sys
        from types import ModuleType
        from qwenpaw.plugins.dependency_usage import (
            DependencyDeclaration,
            DependencyUsageRegistry,
        )
        from qwenpaw.plugins.ownership import RuntimeOwners
        from qwenpaw.plugins.python_backend import PythonBackend

        usage = DependencyUsageRegistry(RuntimeOwners())
        with monkeypatch.context() as patch:
            patch.setattr(sys, "path", list(map(str, paths)))
            loaded = ModuleType(loaded_module)
            loaded.__file__ = str(embedded)
            patch.setitem(sys.modules, loaded_module, loaded)
            for revision in ("first", "second"):
                description = SimpleNamespace(
                    manifest=SimpleNamespace(id="embedded-history"),
                    source_path=tmp_path / revision,
                )
                token = usage.declare(
                    DependencyDeclaration(
                        "embedded-history",
                        revision,
                        (),
                        None,
                    ),
                )
                await PythonBackend.observe_host_dependencies(
                    description,
                    usage,
                    token,
                )
                host = next(
                    use
                    for use in usage.snapshot().uses
                    if use.origin == "host" and use.source_revision == revision
                )
                assert host.snapshot.distributions == imported
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
                (
                    source
                    if change == "relevant" and passes == 2
                    else others[passes - 1]
                ),
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
    sys.stdout.buffer.write(b'READY\\n')
    sys.stdout.buffer.flush()
    assert sys.stdin.readline().strip() == 'RELEASE'
    if sys.argv[3] == 'False':
        marker.unlink()
sys.stdout.buffer.write(b'COMPLETED\\n')
sys.stdout.buffer.flush()
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
