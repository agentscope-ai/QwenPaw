# -*- coding: utf-8 -*-
"""SDK and legacy plugins use main's controlled wheel installation flow."""

# pylint: disable=protected-access
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from qwenpaw.plugins import SDKError, SDKRestartRequiredError
from qwenpaw.plugins.loader import PluginLoader
from qwenpaw.plugins.testing import PluginTestHost

from .test_manifest_dependencies import install_case, package

pytestmark = pytest.mark.p1


@pytest.mark.parametrize("sdk", [False, True])
@pytest.mark.parametrize("repair", [False, True])
def test_install_and_repair_with_controlled_wheels(tmp_path, sdk, repair):
    source = package(tmp_path, ["unified-probe==1.0"], sdk=sdk)
    install_case(tmp_path, source, {"unified-probe"}, repair=repair)


def test_install_failure_preserves_process_output():
    result = PluginLoader._run_subprocess_with_streaming_log(
        [
            sys.executable,
            "-c",
            "import sys; print('No matching distribution found', file=sys.stderr); sys.exit(1)",
        ],
        timeout=10,
        plugin_id="probe",
    )
    assert result.returncode == 1
    assert "No matching distribution found" in result.stdout


@pytest.mark.parametrize("sdk", [False, True])
async def test_common_gate_rejects_host_conflicts_before_resolving(
    tmp_path,
    monkeypatch,
    sdk,
):
    source = package(tmp_path, requirements="uvicorn==0.0.1\n", sdk=sdk)

    def prohibit_install(*_args, **_kwargs):
        pytest.fail("A protected host conflict reached the resolver")

    monkeypatch.setattr(
        PluginLoader,
        "_run_subprocess_with_streaming_log",
        staticmethod(prohibit_install),
    )
    async with PluginTestHost(tmp_path / "host") as host:
        with pytest.raises(
            SDKRestartRequiredError if sdk else SDKError,
            match="uvicorn",
        ) as rejected:
            await host.install(source)
        if not sdk:
            assert rejected.value.__cause__.decision.require_restart


@pytest.mark.parametrize("sdk", [False, True])
async def test_install_lock_failure_never_runs_unlocked(
    tmp_path,
    monkeypatch,
    sdk,
):
    from contextlib import contextmanager
    from qwenpaw.plugins import SDKError, install_lock

    source = package(tmp_path, ["unified-probe==1.0"], sdk=sdk)

    @contextmanager
    def unavailable(*_args, **_kwargs):
        raise install_lock.InstallLockError("INSTALL_LOCK_UNAVAILABLE")
        yield  # pragma: no cover

    def prohibit_install(*_args, **_kwargs):
        pytest.fail("Resolver ran without the framework lock")

    async with PluginTestHost(tmp_path / "host") as host:
        monkeypatch.setattr(install_lock, "plugin_install_lock", unavailable)
        monkeypatch.setattr(
            host._loader,
            "_run_subprocess_with_streaming_log",
            prohibit_install,
        )
        with pytest.raises(SDKError, match="INSTALL_LOCK_UNAVAILABLE"):
            await host.install(source)
        monkeypatch.undo()


@pytest.mark.parametrize("sdk", [False, True])
@pytest.mark.parametrize("frozen", [False, True])
async def test_framework_preserves_large_dependency_timeout(
    tmp_path,
    monkeypatch,
    sdk,
    frozen,
):
    from qwenpaw.plugins import loader as module

    source = package(tmp_path, requirements="openai-whisper\ntorch\n", sdk=sdk)
    path = source / "plugin.json"
    manifest = json.loads(path.read_text())
    manifest["meta"] = {"dependency_install_timeout": 1800}
    path.write_text(json.dumps(manifest))
    loader = PluginLoader([tmp_path])
    monkeypatch.setattr(module, "_is_frozen", lambda: frozen)
    monkeypatch.setattr(module, "require_pip", lambda *_args, **_kwargs: True)
    python = "bundled-python" if frozen else sys.executable

    def run(args, *, timeout, plugin_id, cancel):
        assert timeout == 1800
        assert plugin_id == "extension-contract"
        assert cancel is not None and not cancel.is_set()
        assert args[0] == python
        assert "wheel" in args and "--constraint" in args
        assert "install" not in args
        raise subprocess.TimeoutExpired(args, timeout)

    monkeypatch.setattr(loader, "_run_subprocess_with_streaming_log", run)
    with pytest.raises(RuntimeError, match="1800 s limit"):
        await loader._acquire_dependency_wheels(
            SimpleNamespace(),
            SimpleNamespace(python_executable=python, code_root=source),
            SimpleNamespace(distributions={}, marker_environment={}),
            tmp_path / "site",
            "extension-contract",
            source / "requirements.txt",
            source_path=source,
        )
    assert not loader._dependency_installs


@pytest.mark.parametrize("value", [299, 3601, "1800", True])
def test_invalid_dependency_timeout_is_rejected(tmp_path, value):
    (tmp_path / "plugin.json").write_text(
        json.dumps(
            {
                "meta": {"dependency_install_timeout": value},
            },
        ),
    )
    with pytest.raises(ValueError, match="300..3600"):
        PluginLoader._dependency_install_timeout(tmp_path)
