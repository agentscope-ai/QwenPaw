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
import logging
import subprocess
import sys

import pytest

from qwenpaw.plugins.loader import PluginLoader
from qwenpaw.plugins.execution.dependencies import canonical_environment_path


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    ["already-installed", "unrelated", "retired-root"],
)
async def test_additions_recheck_current_dependency_state(tmp_path, change):
    from dataclasses import replace
    from packaging.markers import default_environment
    from qwenpaw.plugins.dependency_gate import prepare_shared_dependencies
    from qwenpaw.plugins.execution.dependencies import DependencySnapshot

    site = tmp_path / "site"
    site.mkdir()
    required = tmp_path / "requirements.txt"
    required.write_text("needed>=1\n")
    rows = {}
    for name in ("needed", "unrelated"):
        info = site / f"{name}-1.0.dist-info"
        info.mkdir()
        (info / "METADATA").write_text(f"Name: {name}\nVersion: 1.0\n")
        (info / "RECORD").write_text(
            f"{info.name}/METADATA,,\n{info.name}/RECORD,,\n",
        )
        rows[name] = {
            "version": "1.0",
            "metadata_path": str(info),
            "requires_dist": (),
            "top_level": (),
        }
    before = DependencySnapshot(
        sys.executable,
        sys.prefix,
        (str(site),),
        default_environment(),
        ("py3-none-any",),
        {} if change == "already-installed" else {"needed": rows["needed"]},
        (str(site),),
    )
    fresh = replace(before, distributions=rows)

    async def audit(_spec):
        return SimpleNamespace(snapshot=fresh)

    uses = ()
    if change == "retired-root":
        uses = (
            SimpleNamespace(
                read_admitted=True,
                environment=SimpleNamespace(
                    sites=(str(site), str(tmp_path / "retired-search-root")),
                ),
                origin="declaration",
                snapshot=None,
            ),
        )
    usage = SimpleNamespace(
        snapshot=lambda *args, **kwargs: SimpleNamespace(uses=uses),
    )
    result = await prepare_shared_dependencies(
        SimpleNamespace(audit=audit),
        None,
        plugin_id="requester",
        requirements_file=required,
        usage_registry=usage,
        install_target=site,
        expected_snapshot=None if change == "retired-root" else before,
    )
    assert result.distributions == fresh.distributions


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
async def test_dependency_failure_logs_bounded_redacted_pip_tail(
    tmp_path,
    monkeypatch,
    caplog,
):
    from qwenpaw.plugins.dependency_gate import SharedDependencyError

    loader = PluginLoader([tmp_path])
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("sample-sdk==1\n", encoding="utf-8")
    output = (
        "discarded-prefix\n"
        + ("x" * 2000 + "\n") * 20
        + "https://private-user:private-password@example.test/simple"
        "?token=private-query\nAuthorization: Bearer private-auth\n"
        "PIP_INDEX_URL=https://private-user:private-password@example.test/"
        "?token=private-config\nresolver-tail-marker\n"
    )
    fake_pip_script = tmp_path / "fake_pip.py"
    fake_pip_script.write_text(
        f"print({output!r}); raise SystemExit(23)",
        encoding="utf-8",
    )
    popen = subprocess.Popen
    runner = loader._run_subprocess_with_streaming_log
    results = []

    def fake_pip(_command, **kwargs):
        return popen(
            [sys.executable, str(fake_pip_script)],
            **kwargs,
        )

    def run(command, **kwargs):
        result = runner(command, **kwargs)
        results.append(result)
        return result

    monkeypatch.setattr(subprocess, "Popen", fake_pip)
    monkeypatch.setattr(
        "qwenpaw.plugins.loader.require_pip",
        lambda *a, **k: True,
    )
    monkeypatch.setattr(loader, "_run_subprocess_with_streaming_log", run)
    caplog.set_level(logging.INFO)
    with pytest.raises(SharedDependencyError) as caught:
        await loader._acquire_dependency_wheels(
            SimpleNamespace(),
            SimpleNamespace(
                python_executable=sys.executable,
                code_root=tmp_path,
            ),
            SimpleNamespace(distributions={}, marker_environment={}),
            tmp_path / "site",
            "diagnostic-plugin",
            requirements,
        )
    assert caught.value.decision.reason_code == "DEPENDENCY_CONFLICT"
    assert str(caught.value) == (
        "Plugin requirements cannot be resolved for the selected Python environment."
    )
    assert len(results) == 2
    assert all(
        isinstance(result, subprocess.CompletedProcess) for result in results
    )
    assert all(
        result.returncode == 23 and result.stderr == "" for result in results
    )
    assert "diagnostic-plugin" in caplog.text
    assert "pip" in caplog.text.lower() and "23" in caplog.text
    assert "solver" in caplog.text.lower()
    assert "resolver-tail-marker" in caplog.text
    assert "discarded-prefix" not in caplog.text
    assert max(len(line) for line in caplog.text.splitlines()) <= 1200
    assert len(caplog.text.encode()) < 2 * 16 * 1024 + 4096
    for secret in (
        "private-user",
        "private-password",
        "private-query",
        "private-auth",
        "private-config",
    ):
        assert secret not in caplog.text


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
    if case in {
        "missing_package",
        "transitive",
        "repair",
        "stale",
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
        if case in {"missing", "duplicate"}:
            from qwenpaw.plugins.execution.dependencies import (
                read_dependency_inventory,
            )

            view, _ = read_dependency_inventory(
                source,
                (str(site),),
                requirements,
            )
            assert view.warnings
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

    from qwenpaw.plugins import python_backend as backend

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
    from collections import Counter
    from importlib.metadata import PathDistribution
    from qwenpaw.plugins.execution import dependencies as deps
    from qwenpaw.plugins.install_lock import (
        environment_observation,
        observation_inputs,
        observation_write,
    )
    from qwenpaw.plugins.dependency_usage import HostModuleFact

    site, source = tmp_path / "site", tmp_path / "plugin"
    info = site / "sdk-1.0.dist-info"
    info.mkdir(parents=True)
    module = site / "shared_ns/actual.py"
    module.parent.mkdir()
    module.write_text("VALUE = 1\n")
    metadata, record = info / "METADATA", info / "RECORD"
    metadata.write_text(
        "Name: sdk\nVersion: 1.0\nRequires-Dist: child>=1; extra == 'optional'\n\n"
        + "description\n" * 4096,
    )
    record.write_text("shared_ns/actual.py,,\n")
    reads, original = Counter(), PathDistribution.read_text

    def counted(distribution, name):
        if Path(distribution._path) == info:
            reads[name] += 1
        return original(distribution, name)

    monkeypatch.setattr(PathDistribution, "read_text", counted)
    packet = {"code_root": source, "_audit_sites": (site,)}
    fact = HostModuleFact("shared_ns.actual", 1, str(module), (), ())
    async with environment_observation((site,)):
        inputs = observation_inputs()
        async with environment_observation((site,)):
            assert observation_inputs() is inputs
        first = deps.observe_dependencies(packet, _inventory=inputs)
        assert first.distributions["sdk"]["requires_dist"] == (
            "child>=1; extra == 'optional'",
        )
        assert deps.host_module_affected(
            first.distributions["sdk"],
            (fact,),
            record_reads=inputs.setdefault("records", {}),
        )
        again = deps.observe_dependencies(packet, _inventory=inputs)
        assert deps.host_module_affected(
            again.distributions["sdk"],
            (fact,),
            record_reads=inputs["records"],
        )
        assert reads["METADATA"] == reads["RECORD"] == 1
        with observation_write():
            metadata.write_text("Name: sdk\nVersion: 2.0\n")
            record.write_text("unrelated.py,,\n")
        current = deps.observe_dependencies(packet, _inventory=inputs)
        assert current.distributions["sdk"]["version"] == "2.0"
        assert not deps.host_module_affected(
            current.distributions["sdk"],
            (fact,),
            record_reads=inputs.setdefault("records", {}),
        )
        assert reads["METADATA"] == reads["RECORD"] == 2
    assert observation_inputs() is None
    metadata.write_text("Name: sdk\nVersion: 3.0\n")
    async with environment_observation((site,)):
        assert observation_inputs() is not inputs
        current = deps.observe_dependencies(
            packet,
            _inventory=observation_inputs(),
        )
        assert current.distributions["sdk"]["version"] == "3.0"
        assert reads["METADATA"] == 3


def test_host_dependency_record_retains_loaded_ownership(tmp_path):
    import os
    from dataclasses import replace
    from qwenpaw.plugins.execution.dependencies import observe_dependencies
    from qwenpaw.plugins.dependency_usage import (
        DependencyDeclaration,
        DependencyUsageRegistry,
    )
    from qwenpaw.plugins.ownership import RuntimeOwners
    from qwenpaw.plugins.dependency_gate import _host_observation_roots

    info = tmp_path / "sample-1.0.dist-info"
    info.mkdir()
    metadata = info / "METADATA"
    metadata.write_text("Name: sample\nVersion: 1.0\n")
    (info / "RECORD").write_text("shared_ns/loaded.py,,\n")
    packet = {"code_root": tmp_path / "plugin", "_audit_sites": (tmp_path,)}
    snapshot = observe_dependencies(packet)
    # Retain compatibility with existing adapters' strong host observations.
    snapshot = replace(
        snapshot,
        distributions={
            "sample": {
                **snapshot.distributions["sample"],
                "loaded_modules": ("shared_ns.loaded",),
            },
        },
    )
    retired = str(tmp_path / "retired-search-only")
    snapshot = replace(
        snapshot,
        sites=(*snapshot.sites, retired),
        dependency_sites=(*snapshot.dependency_sites, retired),
    )
    usage = DependencyUsageRegistry(RuntimeOwners())
    declaration = DependencyDeclaration("history", "old", (), None)
    old, candidate = usage.declare(declaration), usage.declare(
        replace(declaration, source_revision="candidate"),
    )
    usage.observe_host(old, snapshot)
    roots = _host_observation_roots(
        usage.snapshot().uses,
        (tmp_path,),
        tmp_path,
    )
    assert (
        retired not in roots
        and str(canonical_environment_path(tmp_path)) in roots
    )
    stamp = metadata.stat()
    metadata.write_text("Name: sample\nVersion: 2.0\n")
    os.utime(metadata, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    current = observe_dependencies(packet)
    usage.observe_host(candidate, current)
    usage.observe_host(old, replace(current, distributions={}))
    usage.withdraw(old)
    history = {
        use.source_revision: use
        for use in usage.snapshot().uses
        if use.origin == "host"
    }
    assert history["old"].snapshot.distributions["sample"]["version"] == "1.0"
    assert (
        history["candidate"].snapshot.distributions["sample"]["version"]
        == "2.0"
    )
    assert usage.has_declaration(candidate)


@pytest.mark.asyncio
@pytest.mark.parametrize("withdrawn", [False, True])
async def test_host_dependency_observation_recovers_concurrent_imports(
    tmp_path,
    monkeypatch,
    withdrawn,
):
    import importlib
    from qwenpaw.plugins import python_backend as backend
    from qwenpaw.plugins.dependency_usage import DependencyUsageRegistry
    from qwenpaw.plugins.execution_backend import PluginDescription
    from qwenpaw.plugins.ownership import RuntimeOwners

    site = tmp_path / "site"
    site.mkdir()
    names = [f"_host_recovery_{number}" for number in range(3)]
    for name in names:
        (site / f"{name}.py").write_text("VALUE = 1\n")
    monkeypatch.setattr(sys, "path", [str(site)])
    state, capture = (
        backend._host_dependency_state,
        backend._capture_host_module_facts,
    )
    monkeypatch.setattr(
        backend,
        "_host_dependency_state",
        lambda: (
            state()[0],
            tuple(row for row in state()[1] if row[0] in names),
        ),
    )
    description = PluginDescription(
        SimpleNamespace(id="host-recovery", sdk=None),
        tmp_path / "plugin",
        None,
        None,
        source_identity="original",
        requirements=(),
    )
    usage = DependencyUsageRegistry(RuntimeOwners())
    token = usage.declare(description.dependency_declaration())
    imported = []

    def concurrent(*args, **kwargs):
        facts = capture(*args, **kwargs)
        if len(imported) < 2:
            imported.append(importlib.import_module(names[len(imported) + 1]))
        elif withdrawn:
            usage.withdraw(token)
        return facts

    try:
        importlib.import_module(names[0])
        with monkeypatch.context() as patch:
            patch.setattr(backend, "_capture_host_module_facts", concurrent)
            await backend.PythonBackend.observe_host_dependencies(
                description,
                usage,
                token,
            )
        assert (
            len(imported) == 2 and len(usage.pending_host_observations()) == 1
        )
        # Pending work survives module removal and admission withdrawal.
        for name in names:
            sys.modules.pop(name, None)
        await backend.PythonBackend.reconcile_host_observations(usage)
        host = next(
            use for use in usage.snapshot().uses if use.origin == "host"
        )
        assert (
            host.source_revision == "original" and host.environment is not None
        )
        assert host.snapshot is None
        assert {fact.name for fact in host.host_modules} == set(names)
        assert not usage.pending_host_observations()
        assert usage.has_declaration(token) is not withdrawn
    finally:
        for name in names:
            sys.modules.pop(name, None)
        importlib.invalidate_caches()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "layout",
    ["ordinary", "namespace_alias", "unknown", "zip"],
)
async def test_host_dependency_boundaries_keep_preexisting_and_removed_imports(
    tmp_path,
    monkeypatch,
    layout,
):
    from types import ModuleType
    from importlib.metadata import PathDistribution
    from qwenpaw.plugins import python_backend as backend
    from qwenpaw.plugins.dependency_usage import (
        DependencyDeclaration,
        DependencyUsageRegistry,
    )
    from qwenpaw.plugins.execution.dependencies import host_module_affected
    from qwenpaw.plugins.ownership import RuntimeOwners

    site = tmp_path / "site"
    site.mkdir()
    monkeypatch.setattr(sys, "path", [str(site)])
    source = tmp_path / "plugin"
    source.mkdir()
    description = SimpleNamespace(
        manifest=SimpleNamespace(id="host-history"),
        source_path=source,
    )
    usage = DependencyUsageRegistry(RuntimeOwners())
    token = usage.declare(
        DependencyDeclaration("host-history", "source", (), None),
    )
    names = (
        ["before", "during", "teardown"]
        if layout == "ordinary"
        else ["shared_ns.actual", "plainowner"]
    )
    if layout == "zip":
        names = ["zipped_sdk"]
    state, reads = backend._host_dependency_state, []
    monkeypatch.setattr(
        backend,
        "_host_dependency_state",
        lambda: (
            state()[0],
            tuple(row for row in state()[1] if row[0] in (*names, "own")),
        ),
    )
    read_text = PathDistribution.read_text

    def counted(distribution, name):
        reads.append(name)
        return read_text(distribution, name)

    monkeypatch.setattr(PathDistribution, "read_text", counted)
    for name in names:
        path = site / (name.replace(".", "/") + ".py")
        path.parent.mkdir(exist_ok=True)
        if layout == "zip":
            import zipfile

            archive = site / "bundle.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("zipped_sdk.py", "VALUE = 1\n")
            path = archive / "zipped_sdk.py"
        else:
            path.write_text("VALUE = 1\n")
        module = ModuleType(name)
        module.__file__ = str(path)
        monkeypatch.setitem(sys.modules, name, module)
        await backend.PythonBackend.observe_host_dependencies(
            description,
            usage,
            token,
        )
        monkeypatch.delitem(sys.modules, name)
    own = source / "main.py"
    own.touch()
    module = ModuleType("own")
    module.__file__ = str(own)
    monkeypatch.setitem(sys.modules, "own", module)
    await backend.PythonBackend.observe_host_dependencies(
        description,
        usage,
        token,
    )
    if layout not in {"ordinary", "zip"}:
        namespace = ModuleType("shared_ns")
        namespace.__path__ = [str(site / "shared_ns")]
        monkeypatch.setitem(sys.modules, "shared_ns", namespace)
        names.append("shared_ns")
        await backend.PythonBackend.observe_host_dependencies(
            description,
            usage,
            token,
        )
    initial = usage.host_modules()
    assert {fact.name for fact in initial} == set(names)
    assert (
        not reads
    )  # No metadata, RECORD or wheel-tag audit on cold/stable reads.
    assert all(fact.file_witness for fact in initial)
    # An unrelated path change and a new registry token retain the old facts.
    extra = tmp_path / "extra"
    extra.mkdir()
    sys.path.append(str(extra))
    await backend.PythonBackend.observe_host_dependencies(
        description,
        usage,
        token,
    )
    assert usage.host_modules() == initial and not reads
    usage.withdraw(token)
    assert usage.host_modules() == initial

    # Write-time ownership/shadow checks still cover removed and namespace modules.
    info = site / "replacement-2.0.dist-info"
    info.mkdir()
    (info / "RECORD").write_text(
        (
            (names[0].replace(".", "/") + ".py,,\n")
            if layout != "unknown"
            else "broken,,not-a-size\n"
        ),
    )
    if layout == "zip":
        (info / "RECORD").write_text("bundle.zip,,\n")
    assert host_module_affected({"metadata_path": str(info)}, initial)
    if layout == "namespace_alias":
        (info / "RECORD").write_text("shared_ns/sibling.py,,\n")
        assert not host_module_affected({"metadata_path": str(info)}, initial)
        (info / "RECORD").write_text("shared_ns/__init__.py,,\n")
        assert host_module_affected({"metadata_path": str(info)}, initial)
        from dataclasses import replace
        import os

        namespace = next(fact for fact in initial if fact.namespace)
        with monkeypatch.context() as patch:
            patch.setattr(
                os.path,
                "normcase",
                lambda value: str(value).lower(),
            )
            assert host_module_affected(
                {"metadata_path": str(info)},
                (replace(namespace, name="SHARED_NS"),),
            )
    old_witness = initial[0].file_witness
    Path(initial[0].file_witness[0][0]).write_text("VALUE = 2\n")
    assert usage.host_modules()[0].file_witness == old_witness


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
    from dataclasses import replace
    from types import ModuleType
    from qwenpaw.plugins import python_backend as backend
    from qwenpaw.plugins.dependency_usage import (
        DependencyDeclaration,
        DependencyUsageRegistry,
    )
    from qwenpaw.plugins.ownership import RuntimeOwners
    from qwenpaw.plugins.dependency_gate import evaluate_shared_dependencies

    usage = DependencyUsageRegistry(RuntimeOwners())
    state = backend._host_dependency_state

    async def observe_loaded(name, origin, plugin_id):
        with monkeypatch.context() as patch:
            patch.setattr(sys, "path", list(map(str, paths)))
            loaded = ModuleType(name)
            loaded.__file__ = str(origin)
            patch.setitem(sys.modules, name, loaded)
            patch.setattr(
                backend,
                "_host_dependency_state",
                lambda: (
                    state()[0],
                    tuple(row for row in state()[1] if row[0] == name),
                ),
            )
            description = SimpleNamespace(
                manifest=SimpleNamespace(id=plugin_id),
                source_path=tmp_path / plugin_id,
            )
            token = usage.declare(
                DependencyDeclaration(plugin_id, "first", (), None),
            )
            await backend.PythonBackend.observe_host_dependencies(
                description,
                usage,
                token,
            )
            usage.withdraw(token)
        return next(
            use
            for use in usage.snapshot().uses
            if use.origin == "host" and use.plugin_id == plugin_id
        )

    use = await observe_loaded(loaded_module, embedded, "loaded-owner")
    assert use.snapshot is None
    assert any(
        fact.name == loaded_module and fact.origin == str(embedded)
        for fact in use.host_modules
    )
    stable = evaluate_shared_dependencies(
        None,
        snapshot,
        plugin_id="incoming",
        uses=(use,),
    )
    assert stable.already_satisfied and not stable.require_restart

    import shutil

    public.unlink()
    shutil.rmtree(public_info)
    before = observe_dependencies(packet)
    other_use = None
    if layout == "namespace_overlap":
        other_embedded = nested / "shared_namespace/two.py"
        other_embedded.write_text("VALUE = 'other embedded'\n")
        with (owner_info / "RECORD").open("a") as stream:
            stream.write(f"{other_embedded.relative_to(site).as_posix()},,\n")
        other_use = await observe_loaded(
            "shared_namespace.two",
            other_embedded,
            "loaded-other",
        )
    public.write_text("VALUE = 'public'\n")
    install(site, "sample_sdk", "2.0", [module])
    observed = observe_dependencies(packet)
    decision = evaluate_shared_dependencies(
        None,
        observed,
        plugin_id="incoming",
        uses=(use,),
        installed_distributions=before.distributions,
    )
    if layout == "namespace":
        assert decision.already_satisfied and not decision.require_restart
        return
    assert decision.require_restart
    assert any(
        "host loaded-owner: sample-sdk" in conflict
        for conflict in decision.host_conflicts
    )
    if layout == "owned":
        origin = str(site / "planned_sdk-2.0.dist-info")
        proposed = replace(
            before,
            distributions={
                **before.distributions,
                "planned-sdk": {
                    **observed.distributions["sample-sdk"],
                    "metadata_path": origin,
                },
            },
        )
        addition = evaluate_shared_dependencies(
            None,
            proposed,
            plugin_id="incoming",
            uses=(use,),
            installed_distributions=before.distributions,
            planned_records={origin: "unrelated_sdk.py,,\n"},
        )
        assert addition.already_satisfied and not addition.require_restart
    if other_use is not None:
        for consumers in ((other_use, use), (use, other_use)):
            decision = evaluate_shared_dependencies(
                None,
                observed,
                plugin_id="incoming",
                uses=consumers,
                installed_distributions=before.distributions,
            )
            assert (
                decision.require_restart and len(decision.host_conflicts) == 1
            )
            assert "loaded-owner" in decision.host_conflicts[0]
        # Each new gate reads the changed RECORD, even with restored timestamps.
        stamp = (public_info / "RECORD").stat()
        (public_info / "RECORD").write_text("shared_namespace/two.py,,\n")
        import os

        os.utime(
            public_info / "RECORD",
            ns=(stamp.st_atime_ns, stamp.st_mtime_ns),
        )
        decision = evaluate_shared_dependencies(
            None,
            observed,
            plugin_id="incoming",
            uses=(use, other_use),
            installed_distributions=before.distributions,
        )
        assert decision.require_restart and len(decision.host_conflicts) == 1
        assert "loaded-other" in decision.host_conflicts[0]


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
        assert tmp_path / "site" in admission.targets
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


@pytest.mark.parametrize("shadows_loaded_module", [False, True])
async def test_additions_keep_dependency_inspection_scope_stable(
    tmp_path,
    shadows_loaded_module,
):
    """A newly reachable dependency is inspected equally before/after writes."""
    import hashlib
    import zipfile

    from qwenpaw.plugins.dependency_gate import (
        SharedDependencyError,
        prepare_shared_dependencies,
    )
    from qwenpaw.plugins.dependency_usage import HostModuleFact
    from qwenpaw.plugins.execution.dependencies import (
        observe_dependencies,
        repair_marker,
    )
    from qwenpaw.plugins.wheel_additions import WheelAddition
    from .test_manifest_dependencies import write_wheel

    site = tmp_path / "site"
    owner = write_wheel(
        tmp_path,
        "audit-owner",
        payload={
            "audit-owner-extra.pth": "# Existing file, discovered by a deeper audit\n",
            "audit_owner/_vendor/loaded_external.py": "VALUE = 'embedded'\n",
        },
    )
    with zipfile.ZipFile(owner) as archive:
        archive.extractall(site)
    before = {
        str(p.relative_to(site)): p.read_bytes()
        for p in site.rglob("*")
        if p.is_file()
    }
    wheel = write_wheel(
        tmp_path,
        "audit-request",
        metadata_headers="Requires-Dist: audit-owner>=1\n",
        payload={"loaded_external.py": "VALUE = 'public'\n"}
        if shadows_loaded_module
        else {},
    )
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("audit-request==1.0\n")
    packet = {
        "code_root": str(tmp_path / "candidate"),
        "_audit_sites": [str(site)],
        "_requirements": ["audit-request==1.0"],
    }
    initial = observe_dependencies(packet)
    assert initial.distributions["audit-owner"]["top_level"] == (
        "audit_owner",
    )
    facts = tuple(
        HostModuleFact(name, 1, str(site / path), (), ())
        for name, path in (
            ("audit_owner", "audit_owner/__init__.py"),
            ("loaded_external", "audit_owner/_vendor/loaded_external.py"),
        )
    )
    use = SimpleNamespace(
        origin="host",
        plugin_id="running-hub",
        host_modules=facts,
        snapshot=None,
        read_admitted=False,
        environment=SimpleNamespace(sites=(str(site),)),
    )
    usage = SimpleNamespace(
        snapshot=lambda *args, **kwargs: SimpleNamespace(uses=(use,)),
    )

    async def audit(_spec):
        return SimpleNamespace(snapshot=observe_dependencies(packet))

    install = prepare_shared_dependencies(
        SimpleNamespace(audit=audit),
        None,
        plugin_id="incoming",
        requirements_file=requirements,
        usage_registry=usage,
        install_target=site,
        wheels=(
            WheelAddition(
                wheel,
                hashlib.sha256(wheel.read_bytes()).hexdigest(),
            ),
        ),
    )
    if shadows_loaded_module:
        with pytest.raises(
            SharedDependencyError,
            match="audit-request.*shadows",
        ):
            await install
        assert not (site / "audit_request").exists()
    else:
        result = await install
        assert result.distributions["audit-request"]["version"] == "1.0"
        assert (
            "audit-owner-extra"
            in result.distributions["audit-owner"]["top_level"]
        )
        assert (site / "audit_request/__init__.py").is_file()
    assert all(
        (site / path).read_bytes() == content
        for path, content in before.items()
    )
    assert not repair_marker(site).exists()
