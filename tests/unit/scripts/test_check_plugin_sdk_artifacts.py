# -*- coding: utf-8 -*-
"""Validate bundled local artifacts and standalone acceptance test scopes."""

import io
import os
from pathlib import Path
import runpy
import shlex
import subprocess
import sys
import tarfile
import zipfile

import pytest
import yaml

pytestmark = pytest.mark.p1


def test_acceptance_suites_collect_outside_checkout(tmp_path):
    source = Path(__file__).resolve().parents[3]
    checker = runpy.run_path(
        str(source / "scripts/check_plugin_sdk_artifacts.py"),
    )
    calls = []
    selected = checker["prepare_author_tests"](source, tmp_path)
    checker["run_acceptance_tests"](
        lambda name, *args: calls.append(args),
        source,
        tmp_path,
        local_provider=True,
    )
    assert "test_sdk_install_transaction.py" in selected
    assert not {
        "test_sdk_channel_routing_contract.py",
        "test_sdk_provider_contract.py",
        "test_sdk_native_provider_contract.py",
        "test_sdk_resource_contract.py",
    }.intersection(selected)
    assert "test_sdk_dependency_environment.py" not in selected
    code = """
import importlib.abc
import sys
import pytest

class NoRepositoryTests(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "tests" or fullname.startswith("tests."):
            raise AssertionError("Repository test import: " + fullname)

sys.meta_path.insert(0, NoRepositoryTests())
raise SystemExit(pytest.main([
    *sys.argv[1:], "--collect-only", "-q", "--tb=short",
]))
"""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("PYTHON", "QWENPAW_"))
    }
    env.update(
        QWENPAW_DEPENDENCY_STATE_DIR=str(tmp_path / "dependency-state"),
        QWENPAW_WORKING_DIR=str(tmp_path / "working"),
        QWENPAW_SECRET_DIR=str(tmp_path / "secrets"),
    )
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            code,
            *[node for args in calls for node in args[2:-3]],
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "test_sdk_install_transaction.py::" in result.stdout
    assert (
        "test_bundle_load_does_not_import_backend_or_download_packages"
        in result.stdout
    )
    assert (
        "test_local_dataclasses_preserve_management_http_responses"
        in result.stdout
    )
    assert "test_turn_lease_survives_between_model_calls" not in result.stdout
    assert "tests collected" in result.stdout


@pytest.mark.parametrize("selected", [None, ["test_sdk_harness.py"]])
@pytest.mark.parametrize("local_provider", [False, True])
def test_acceptance_scope_is_explicit(
    tmp_path,
    selected,
    local_provider,
):
    source = Path(__file__).resolve().parents[3]
    checker = runpy.run_path(
        str(source / "scripts/check_plugin_sdk_artifacts.py"),
    )
    argv = [
        "--wheel",
        str(tmp_path / "test.whl"),
        "--sdist",
        str(tmp_path / "test.tar.gz"),
        "--python",
        sys.executable,
        "--source-root",
        str(source),
        "--output",
        str(tmp_path),
    ]
    if local_provider:
        argv.append("--local-provider")
    if selected:
        argv.extend(["--test-files", *selected])
    args = checker["_parse_args"](argv)
    tests = checker["prepare_author_tests"](
        source,
        tmp_path,
        args.test_files,
    )
    calls = {}
    checker["run_acceptance_tests"](
        lambda name, *args: calls.update({name: args}),
        source,
        tmp_path,
        local_provider=args.local_provider,
    )
    assert ("installed-local-provider-tests" in calls) is local_provider
    assert (tmp_path / "local_provider_tests").exists() is local_provider
    assert calls["public-author-tests"] == (
        "-m",
        "pytest",
        str(tmp_path / "author_tests"),
        "-q",
        "--tb=short",
        "--timeout=45",
    )
    if selected:
        assert tests == selected
        assert not (
            tmp_path / "author_tests/test_sdk_channel_contract.py"
        ).exists()
    else:
        assert "test_sdk_channel_contract.py" in tests
        assert "test_sdk_install_transaction.py" in tests
    assert "test_sdk_native_provider_contract.py" not in tests


@pytest.mark.parametrize(
    "workflow,local_provider,test_files",
    [
        ("tests.yml", False, None),
        ("harness-plugin-tests.yml", False, ["test_sdk_harness.py"]),
        (
            "local-model-plugin-tests.yml",
            True,
            ["test_sdk_context_lifecycle.py"],
        ),
    ],
)
def test_ci_artifact_scope_matches_installed_extras(
    workflow,
    local_provider,
    test_files,
):
    source = Path(__file__).resolve().parents[3]
    checker = runpy.run_path(
        str(source / "scripts/check_plugin_sdk_artifacts.py"),
    )
    config = yaml.safe_load(
        (source / ".github/workflows" / workflow).read_text(encoding="utf-8"),
    )
    checked = 0
    for job in config["jobs"].values():
        commands = "\n".join(
            step.get("run", "") for step in job.get("steps", [])
        )
        for line in commands.replace("\\\n", " ").splitlines():
            script = "scripts/check_plugin_sdk_artifacts.py"
            if script not in line:
                continue
            argv = shlex.split(line, comments=True)
            if script not in argv:
                continue
            args = checker["_parse_args"](argv[argv.index(script) + 1 :])
            assert args.local_provider is local_provider
            if local_provider:
                assert (
                    "plugins/provider/local-llamacpp/requirements.txt"
                    in commands
                )
            assert args.test_files == test_files
            checked += 1
    assert checked, "No artifact checker invocation found"


@pytest.mark.parametrize("format", ["wheel", "sdist"])
@pytest.mark.parametrize("fault", [None, "python", "metadata", "content"])
def test_local_provider_artifact_preserves_source_files(
    tmp_path,
    format,
    fault,
):
    source = tmp_path / "source"
    local = source / "plugins/provider/local-llamacpp"
    local.mkdir(parents=True)
    files = {
        "plugin.py": b"from . import manager\n",
        "manager.py": b"class Manager: pass\n",
        "plugin.json": b"{}",
        "requirements.txt": b"",
        "runtime-release.json": b"{}",
    }
    for name, content in files.items():
        (local / name).write_bytes(content)
    if fault == "python":
        del files["manager.py"]
    elif fault == "metadata":
        del files["runtime-release.json"]
    elif fault == "content":
        files["plugin.py"] = b"raise RuntimeError('stale plugin')\n"
    artifact = tmp_path / ("test.whl" if format == "wheel" else "test.tar.gz")
    if format == "wheel":
        with zipfile.ZipFile(artifact, "w") as archive:
            for name, content in files.items():
                archive.writestr(
                    "qwenpaw/plugins/bundled/provider/local-llamacpp/" + name,
                    content,
                )
    else:
        with tarfile.open(artifact, "w:gz") as archive:
            for name, content in files.items():
                member = tarfile.TarInfo(
                    "test/plugins/provider/local-llamacpp/" + name,
                )
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
    checker = runpy.run_path(
        str(
            Path(__file__).resolve().parents[3]
            / "scripts/check_plugin_sdk_artifacts.py",
        ),
    )
    if fault:
        with pytest.raises(AssertionError, match="[Ll]ocal provider"):
            checker["check_local_provider_artifact"](artifact, source)
    else:
        checker["check_local_provider_artifact"](artifact, source)
